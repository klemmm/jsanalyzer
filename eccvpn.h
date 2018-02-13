#ifndef ECCVPN_H 
#define ECCVPN_H 1

/* user-configurable area */

#define LINK_MTU 1500UL
#define RUN_AS_UID 65534 
#define RUN_AS_GID 65534
#define CHROOT_DIR "/tmp/"
#define INTERLEAVE 4

/* Disable HMAC only if you know what you're doing (using eccvpn on top of ipsec, etc.) */
/* #define DISABLE_HMAC 1 */
#define HMAC_SECRET (void*) "OfUao162QT3AU6YmBkaQWLVLSQ" /* Change this, put same value on both ends */

#endif

