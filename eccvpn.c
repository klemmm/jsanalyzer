#include <netinet/in.h>
#include <sys/ioctl.h>
#include <netinet/ip.h>
#include <fcntl.h>
#include <linux/if_tun.h>
#include <time.h>
#include <net/if.h>
#include <sys/ioctl.h>
#include <sys/select.h>
#include <arpa/inet.h>
#include <stdint.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <assert.h>
#include <sys/uio.h>
#include <errno.h>
#include <syslog.h>
#include <mhash.h>

#include "eccvpn.h"
#include "ecc.h"


#define RECEIVE_TIMEOUT 10800
#define PACKET_SIZE (LINK_MTU - 28) /* 20bytes ip + 8bytes udp */
#define PAYLOAD_SIZE (PACKET_SIZE - sizeof(header_t))

#define BEFORE_OR_EQUAL(a,b) (((b) - (a)) < 0x80000000)
#define BEFORE(a,b) (BEFORE_OR_EQUAL(a,b) && ((a) != (b)))
#define AFTER(a,b) BEFORE(b,a)
#define AFTER_OR_EQUAL(a,b) BEFORE_OR_EQUAL(b,a)

#define MAX(a,b) (((a) > (b)) ? (a) : (b))

/* On-the-wire packet header */
typedef struct {
	uint32_t seq;
	uint8_t idx;
#ifndef DISABLE_HMAC
#define HMAC_TYPE MHASH_SHA1
#define HMAC_SIZE 20
	uint8_t hmac[HMAC_SIZE];
#endif
} header_t;

// In-memory packet representation (some useless fields are omitted)
typedef struct {
	size_t size; // actual payload size (without encap header, as seen on tun interface)
	uint8_t data[PAYLOAD_SIZE];
} packet_t;

#define DATA_SIZE 		16U // number of actual data packets
#define CHECK_SIZE		NPAR // number of control (EC) packets (defined to 4 in rscode lib)
#define TOTAL_SIZE		(DATA_SIZE + CHECK_SIZE)
typedef struct {
	packet_t pkt[TOTAL_SIZE];
	time_t age;
} group_t;

typedef struct {
	// common info
	int client;
	struct sockaddr_in peer;
	struct sockaddr_in local;
	struct sockaddr_in from;
	int peer_known;
	int tunfd;
	int sockfd;

	// receiver state
	uint32_t seq_rcv;
	uint32_t seq_first;
#define HIST_SIZE 		0x10000
	uint8_t rcv_count[HIST_SIZE];
	group_t *rcv_groups[HIST_SIZE];
	size_t rcv_size[HIST_SIZE];
	time_t last_receive;
	uint32_t rcv_total;
	uint32_t rcv_rec;
	uint32_t rcv_fail;

	// sender state
	uint32_t seq_snd;
	uint8_t npkt;
	uint8_t snd_il;
	group_t snd_group[INTERLEAVE];
	size_t snd_size[INTERLEAVE];
} tunnel_t;

struct sockaddr_in null_addr;

uint16_t ip_chksum(uint8_t *buffer, int length)
{
	uint16_t *w = (u_short *)buffer;
	uint32_t sum    = 0;  
	uint16_t pad_val = 0;
	uint32_t pad = (unsigned)length % 2;
	if (pad) {
		pad_val = buffer[length - 1];
	}

	length >>= 1;
	while(length--)  
		sum += *w++;

	if (pad)
		sum += pad_val;
	sum = (sum >> 16) + (sum & 0xffff);
	return (uint16_t) (~((sum >> 16) + sum));
}

void tunnel_encode(group_t *grp, size_t max_size) {
	uint8_t i;
	size_t j;
	uint8_t msg[DATA_SIZE];
	uint8_t codeword[TOTAL_SIZE];

	for (j = 0; j < max_size; j++) {
		for (i = 0; i < DATA_SIZE; i++) {
			msg[i] = grp->pkt[i].data[j];
		}
		encode_data(msg, DATA_SIZE, codeword);

		for (i = DATA_SIZE; i < TOTAL_SIZE; i++) {
			grp->pkt[i].data[j] = codeword[i];
		}
	}
	for (i = DATA_SIZE; i < TOTAL_SIZE; i++) {
		grp->pkt[i].size = max_size;
	}
}

void tunnel_decode(group_t *grp, size_t max_size) {
	uint8_t erased[TOTAL_SIZE];
	int erasures[TOTAL_SIZE];
	int nerasures = 0;
	uint8_t i;
	size_t j;
	uint8_t codeword[TOTAL_SIZE];
	struct iphdr *iph;
	int real_erasures = 0;

	for (i = 0; i < TOTAL_SIZE; i++) {
		if (grp->pkt[i].size == 0) {
			erasures[nerasures++] = (signed) TOTAL_SIZE - i - 1;
			erased[i] = 1;
			if (i < DATA_SIZE)
				real_erasures++;
		} else {
			grp->pkt[i].size = 0;
			erased[i] = 0;
		}
	}
	if (real_erasures == 0)
		return;
	assert(nerasures == CHECK_SIZE);
	for (j = 0; j < max_size; j++) {
		for (i = 0; i < TOTAL_SIZE; i++) {
			codeword[i] = grp->pkt[i].data[j];
		}
		decode_data(codeword, TOTAL_SIZE);
		if (check_syndrome() != 0) {
			correct_errors_erasures(codeword, TOTAL_SIZE, nerasures, erasures);
		}
		for (i = 0; i < DATA_SIZE; i++) {
			grp->pkt[i].data[j] = codeword[i];
		}
	}
	for (i = 0; i < DATA_SIZE; i++) {
		if (erased[i]) {
			iph = (struct iphdr*) grp->pkt[i].data;
			if (ip_chksum((void*)iph, iph->ihl << 2) != 0) {
				syslog(LOG_WARNING, "Invalid IP checksum!");
			} 
			if (htons(iph->tot_len) > PAYLOAD_SIZE) {
				syslog(LOG_WARNING, "Invalid recovered packet size %u (ignored)", htons(iph->tot_len));
			} else grp->pkt[i].size = htons(iph->tot_len);
		}
	}
	return;
}

void tunnel_free_grp(tunnel_t *tun, uint16_t grpid) {
	free(tun->rcv_groups[grpid]);
	tun->rcv_groups[grpid] = NULL;
}

void tunnel_recycle_grp(tunnel_t *tun, uint16_t grpid) {
	if (tun->rcv_count[grpid] == 0) {
		//assert(tun->rcv_groups[grpid] == NULL);
	} else {
		if (tun->rcv_count[grpid] == TOTAL_SIZE) {
			//assert(tun->rcv_groups[grpid] == NULL);
			tun->rcv_total += DATA_SIZE;
		}
		if ((tun->rcv_count[grpid] < TOTAL_SIZE) && (tun->rcv_count[grpid] >= DATA_SIZE)) {
			//assert(tun->rcv_groups[grpid] == NULL);
			tun->rcv_total += DATA_SIZE;
			tun->rcv_rec++;
		}
		if (tun->rcv_count[grpid] < DATA_SIZE) {
			if ((grpid != (tun->seq_rcv % HIST_SIZE)) && (grpid != (tun->seq_first % HIST_SIZE))){
				tun->rcv_fail += DATA_SIZE - tun->rcv_count[grpid];
				syslog(LOG_WARNING, "Insufficient data to repair group %u (dropped %u packets)", grpid, DATA_SIZE - tun->rcv_count[grpid]);
			}
			tun->rcv_total += tun->rcv_count[grpid];
			tunnel_free_grp(tun, grpid);
		}
		tun->rcv_count[grpid] = 0;
	}
	tun->rcv_size[grpid] = 0;
}


int force_reset = 0;
void sighandler(int crap) {
	(void) crap;
	signal(SIGUSR1, &sighandler);
	force_reset = 1;
}
void quit(int crap) {
	(void) crap;
	syslog(LOG_NOTICE, "Exiting due to signal...");
	exit(0);
}


void tunnel_decaps(tunnel_t *tun, const uint8_t *buf, size_t count) {
	uint32_t i;
	header_t *hdr = (header_t *) buf;
	const uint8_t *payload = buf + sizeof(header_t); 
	uint16_t grp_id;
	time_t now;
#ifndef DISABLE_HMAC
	MHASH mh;
	uint8_t hmac[HMAC_SIZE];
#endif

	assert(count <= PACKET_SIZE);
	if (count < sizeof(header_t) + sizeof(struct iphdr)) {
		syslog(LOG_WARNING, "Invalid packet received (size %lu)", count);
		return;
	}
	if (tun->seq_first == 0)
		tun->seq_first = hdr->seq;
#ifndef DISABLE_HMAC

	mh = mhash_hmac_init(HMAC_TYPE, HMAC_SECRET, sizeof(HMAC_SECRET), mhash_get_hash_pblock(HMAC_TYPE));
	mhash(mh, payload, (uint32_t) (count - sizeof(header_t)));
	mhash_hmac_deinit(mh, hmac);
	if (memcmp(hmac, hdr->hmac, HMAC_SIZE) != 0) {
		syslog(LOG_WARNING, "Dropped packet with invalid HMAC");
		return;
	}
#endif
//	printf("[DEBUG] Received packet of seq %x idx %x (%s)\n", hdr->seq, hdr->idx, (hdr->idx < DATA_SIZE) ? "DATA" : "ECC");
	if (!tun->client && (memcmp(&tun->from, &tun->peer, sizeof(struct sockaddr_in)) != 0)) {
		char *ipstr = inet_ntoa(tun->from.sin_addr);
		memcpy(&tun->peer, &tun->from, sizeof(struct sockaddr_in));
		syslog(LOG_NOTICE, "New peer address: %s:%u", ipstr, htons(tun->peer.sin_port));
		tun->peer_known = 1;
	}
	now = time(NULL);
	if (force_reset || (tun->last_receive + RECEIVE_TIMEOUT < now) || AFTER(hdr->seq, tun->seq_rcv + HIST_SIZE - 1)) {
		if (force_reset) {
			syslog(LOG_NOTICE, "Extended report:");
			for (i = 0; i < HIST_SIZE; i++) {
				uint16_t hist_seq = (uint16_t) (tun->seq_rcv >> 16);
				uint16_t cur_grp = tun->seq_rcv & 0xFFFF;
				if (cur_grp < i)
					hist_seq--;
				uint8_t numpkt = tun->rcv_count[i];
				if ((numpkt != TOTAL_SIZE) && (numpkt != 0)) {
					uint8_t j;
					char missing[1024];
					strcpy(missing, "");
					for (j = 0; j < TOTAL_SIZE; j++) {
						char str[16];
						if (tun->rcv_groups[i]->pkt[j].size == 0) {
							snprintf(str, 16, "%u ", j);
							strcat(missing, str);
						}

					}
					syslog(LOG_NOTICE, "For group %x we received %u packets. Missing=%s", (uint32_t)(hist_seq << 16) | i, numpkt, missing);
				}

			}
		}
		syslog(LOG_NOTICE, "Synchronizing state with peer.");
		for (i = 0; i < HIST_SIZE; i++)
			tunnel_recycle_grp(tun, (uint16_t) i);
		if (force_reset) {
			syslog(LOG_NOTICE, "Summary: total=%u recovered=%u failed=%u", tun->rcv_total, tun->rcv_rec, tun->rcv_fail);
			force_reset = 0;
		}
		tun->seq_rcv = hdr->seq;
		tun->seq_first = tun->seq_rcv;
		tun->rcv_total = 0;
		tun->rcv_rec = 0;
		tun->rcv_fail = 0;
	}
	tun->last_receive = now;
	
	if (BEFORE_OR_EQUAL(hdr->seq, (tun->seq_rcv - HIST_SIZE))) {
		syslog(LOG_WARNING, "Dropped late packet with seq: %u", hdr->seq);
		return;
	} else if (AFTER(hdr->seq, tun->seq_rcv)) {
		int lala;
		lala = 0;
		for (i = ((tun->seq_rcv + 1) % HIST_SIZE); i != (uint16_t)(hdr->seq % HIST_SIZE); i = ((i + 1) % HIST_SIZE)) {
			tunnel_recycle_grp(tun, (uint16_t) i);
			lala++;
		}
		tunnel_recycle_grp(tun, (uint16_t) (hdr->seq % HIST_SIZE));
		tun->seq_rcv = hdr->seq;
	} 

	grp_id = (uint16_t)hdr->seq % HIST_SIZE;

	if (tun->rcv_count[grp_id] == TOTAL_SIZE) {
		syslog(LOG_WARNING, "Duplicate packet in group: %d", grp_id);
		return; 
	}
	tun->rcv_count[grp_id]++;
	if (tun->rcv_count[grp_id] > DATA_SIZE) {
		return; // Last packet was already recovered
	}

	write(tun->tunfd, payload, count - sizeof(header_t));
	if (tun->rcv_count[grp_id] == 1) {
		// First packet in group, allocate buffer
		//assert(tun->rcv_groups[grp_id] == NULL);
		if (tun->rcv_groups[grp_id] != NULL)
			free(tun->rcv_groups[grp_id]);
		tun->rcv_groups[grp_id] = malloc(sizeof(group_t));
		memset(tun->rcv_groups[grp_id], 0, sizeof(group_t));
	}
	memcpy(tun->rcv_groups[grp_id]->pkt[hdr->idx].data, payload, count - sizeof(header_t));
	tun->rcv_groups[grp_id]->pkt[hdr->idx].size = count - sizeof(header_t);
	tun->rcv_groups[grp_id]->age = time(NULL);

	if (tun->rcv_size[grp_id] < (count - sizeof(header_t)))
		tun->rcv_size[grp_id] = count - sizeof(header_t);

	if (tun->rcv_count[grp_id] == DATA_SIZE) {
		tunnel_decode(tun->rcv_groups[grp_id], tun->rcv_size[grp_id]);
		// ECC recovered missing packets in group. Maybe they will arrive later, we don't care, we deliver them ASAP.
		for (i = 0; i < DATA_SIZE; i++) {
			if (tun->rcv_groups[grp_id]->pkt[i].size > 0) {
				write(tun->tunfd, tun->rcv_groups[grp_id]->pkt[i].data, tun->rcv_groups[grp_id]->pkt[i].size);
			}
		}
		// tunnel_free_grp(tun, grp_id);
	} 
}

void tunnel_encaps(tunnel_t *tun, uint8_t *data, size_t count) {
	struct iovec iov[2];
	uint8_t i,j;
	header_t *hdr = (void*) data;
	uint8_t *buf = data + sizeof(header_t);
#ifndef DISABLE_HMAC
	MHASH mh;
#endif

	assert(count <= PAYLOAD_SIZE);
	hdr->seq = tun->seq_snd + tun->snd_il;
	hdr->idx = tun->npkt;
#ifndef DISABLE_HMAC
	mh = mhash_hmac_init(HMAC_TYPE, HMAC_SECRET, sizeof(HMAC_SECRET), mhash_get_hash_pblock(HMAC_TYPE));
	mhash(mh, buf, (uint32_t) count);
	mhash_hmac_deinit(mh, hdr->hmac);
#endif
	if (tun->client) {
		write(tun->sockfd, data, count + sizeof(header_t));
	} else sendto(tun->sockfd, data, count + sizeof(header_t), 0, (struct sockaddr *) &tun->peer, sizeof(struct sockaddr_in));
	memcpy(tun->snd_group[tun->snd_il].pkt[tun->npkt].data, buf, count);
	tun->snd_group[tun->snd_il].pkt[tun->npkt].size = count;
	if (count > tun->snd_size[tun->snd_il])
		tun->snd_size[tun->snd_il] = count;

	if ((tun->snd_il == (INTERLEAVE - 1)) && (tun->npkt == (DATA_SIZE - 1))){
		for (j = 0; j < INTERLEAVE; j++)
			tunnel_encode(&tun->snd_group[j], tun->snd_size[j]);
		iov[0].iov_base = hdr;
		iov[0].iov_len = sizeof(header_t);
		if (!tun->client)
			if (connect(tun->sockfd, (struct sockaddr *) &tun->peer, sizeof(struct sockaddr_in)) == -1) {
				syslog(LOG_ERR, "ERROR: connect: %s\n", strerror(errno));
				exit(1);
			}
		for (i = DATA_SIZE; i < TOTAL_SIZE; i++) {
			for (j = 0; j < INTERLEAVE; j++) {
//				printf("sending ecc %d %d\n", i, j);
				iov[1].iov_base = tun->snd_group[j].pkt[i].data;
				iov[1].iov_len = tun->snd_group[j].pkt[i].size;
				hdr->idx = i;
				hdr->seq = tun->seq_snd + j;
#ifndef DISABLE_HMAC
				mh = mhash_hmac_init(HMAC_TYPE, HMAC_SECRET, sizeof(HMAC_SECRET), mhash_get_hash_pblock(HMAC_TYPE));
				mhash(mh, iov[1].iov_base, (uint32_t) iov[1].iov_len);
				mhash_hmac_deinit(mh, hdr->hmac);
#endif
				writev(tun->sockfd, iov, 2);
			}
		}
		if (!tun->client)
			if (connect(tun->sockfd, (struct sockaddr *) &null_addr, sizeof(struct sockaddr_in)) == -1) {
				syslog(LOG_ERR, "ERROR: connect: %s\n", strerror(errno));
				exit(1);
			}
	}

	tun->snd_il = (tun->snd_il + 1U) % INTERLEAVE;
	if (tun->snd_il == 0)
		tun->npkt = (tun->npkt + 1U) % DATA_SIZE;
	if ((tun->snd_il == 0) && (tun->npkt == 0)) {
		memset(tun->snd_group, 0, sizeof(tun->snd_group));
		memset(tun->snd_size, 0, sizeof(tun->snd_size));
		tun->seq_snd = tun->seq_snd + INTERLEAVE;
	}
}

tunnel_t *tunnel_create(char *name, in_addr_t local, in_addr_t remote, uint16_t lport, uint16_t rport) {
	tunnel_t *t = malloc(sizeof(tunnel_t));
	int fd, sock;
	struct ifreq ifr;
	struct sockaddr_in la, ra;

	memset(t, 0, sizeof(tunnel_t));
	if ((fd = open("/dev/net/tun", O_RDWR)) < 0 ) {
		perror("open tun");
		exit(1);
	}
	memset(&ifr, 0, sizeof(ifr));
	ifr.ifr_flags = IFF_TUN | IFF_NO_PI;
	strncpy(ifr.ifr_name, name, IFNAMSIZ);
	if (ioctl(fd, TUNSETIFF, (void *) &ifr) < 0 ) { 
		perror("ioctl TUNSETIFF");
		exit(1);
	}

	t->tunfd = fd;

	sock = socket(AF_INET, SOCK_DGRAM, 0);
	ifr.ifr_addr.sa_family = AF_INET;
	ifr.ifr_mtu = PAYLOAD_SIZE; 
	if (ioctl(sock, SIOCSIFMTU, (caddr_t)&ifr) < 0) {
		perror("ioctl SIOCSIFMTU");
		exit(1);
	}
	memset(&la, 0, sizeof(la));
	memset(&ra, 0, sizeof(ra));

	la.sin_family = AF_INET;
	la.sin_port = htons(lport);
	la.sin_addr.s_addr = local;

	ra.sin_family = AF_INET;
	ra.sin_port = htons(rport);
	ra.sin_addr.s_addr = remote;

	if (bind(sock, (struct sockaddr *) &la, sizeof(struct sockaddr_in)) == -1) {
		perror("bind");
		exit(1);
	}
	memcpy(&t->local, &la, sizeof(struct sockaddr_in));

	if ((ra.sin_addr.s_addr != INADDR_ANY) && (ra.sin_port != 0)) {
		if (connect(sock, (struct sockaddr *) &ra, sizeof(struct sockaddr_in)) == -1) {
			perror("connect");
			exit(1);
		}
		printf("Using client mode...\n");
		t->client = 1;
		memcpy(&t->peer, &ra, sizeof(struct sockaddr_in));
	} else {
		printf("Using server mode...\n");
		t->client = 0;
	}

	t->sockfd = sock;
	t->seq_snd = ((uint32_t)time(NULL) & 0xFFFF) << 16;
	t->last_receive = 0;
	tunnel_recycle_grp(t, 0);
	return t;
}

void daemonize() {
	int r = fork();
	if (r == -1) {
		perror("fork");
		exit(1);
	}
	if (r != 0) {
		printf("Daemon successfully started.\n");
		exit(0);
	}
	close(0);
	close(1);
	close(2);
	if (fork() == 0) {
		if (setsid() == -1)
			exit(0);
	} else {
		exit(0);
	}
}

void revoke_privileges() {
	if (chdir(CHROOT_DIR) == -1) {
		perror("chdir");
		exit(-1);
	}

	if (chroot(CHROOT_DIR) == -1) {
		perror("chroot");
		exit(-1);
	}
	if (setgid(RUN_AS_GID) == -1) {
		perror("setgid");
		exit(-1);
	}

	if (setuid(RUN_AS_UID) == -1) {
		perror("setuid");
		exit(-1);
	}
}


int main(int argc, char **argv) {
	tunnel_t *tun;

	if (argc != 5) {
		fprintf(stderr, "usage: %s <tun iface name> <remote host> <local port> <remote port>\n", argv[0]);
		exit(1);
	}

	memset(&null_addr, 0, sizeof(struct sockaddr_in));
	null_addr.sin_family = AF_UNSPEC;

	tun = tunnel_create(argv[1], INADDR_ANY, inet_addr(argv[2]), (uint16_t) atoi(argv[3]), (uint16_t) atoi(argv[4]));
	openlog ("eccvpn", LOG_PID | LOG_NDELAY | LOG_CONS, LOG_DAEMON);

	revoke_privileges();

#ifndef NODAEMON
	daemonize();
#endif

	signal(SIGUSR1, &sighandler);
	signal(SIGINT, &quit);
	signal(SIGTERM, &quit);

	syslog(LOG_NOTICE, "Starting up...");

	initialize_ecc();

	for (;;) {
		fd_set fds;
		int r;
		ssize_t s;
		uint8_t buf[PACKET_SIZE];

		FD_ZERO(&fds);
		FD_SET(tun->sockfd, &fds);
		FD_SET(tun->tunfd, &fds);

		r = select(MAX(tun->sockfd, tun->tunfd) + 1, &fds, NULL, NULL, NULL);
		if (r == -1) {
			if (errno == EINTR)
				continue;
			syslog(LOG_ERR, "ERROR: select returned error: %s", strerror(errno));
			exit(1);
		}
		if (FD_ISSET(tun->sockfd, &fds)) {
			if (tun->client) {
				s = read(tun->sockfd, buf, PACKET_SIZE);
			} else {
				memset(&tun->from, 0, sizeof(struct sockaddr_in));
				socklen_t fromlen = sizeof(struct sockaddr_in);
				s = recvfrom(tun->sockfd, buf, PACKET_SIZE, 0, (struct sockaddr *) &tun->from, &fromlen);
			}
			if (s < 0) {
				if (errno != ECONNREFUSED) {
					syslog(LOG_ERR, "ERROR: failed to read udp socket: %s", strerror(errno));
					exit(1);
				}
			} else if (s > 0)
				tunnel_decaps(tun, buf, (size_t)s);

		}
		if (FD_ISSET(tun->tunfd, &fds)) {
			s = read(tun->tunfd, buf + sizeof(header_t), PAYLOAD_SIZE);
			if (s <= 0) {
				syslog(LOG_ERR, "ERROR: failed to read tun device: %s", strerror(errno));
				exit(1);
			}
			if (tun->client || tun->peer_known)
				tunnel_encaps(tun, buf, (size_t)s);
		}
	}

	return 0;
}
