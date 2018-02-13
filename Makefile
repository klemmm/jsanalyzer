CFLAGS=-I./rscode/ -Wall -Wextra -Wconversion -Wsign-compare -Wsign-conversion -W -O3 -march=native -Wall -W -Wshadow -Wunused-variable -Wunused-parameter -Wunused-function -Wunused -Wno-system-headers -Wwrite-strings -pedantic
LDFLAGS=-L./rscode/
LDLIBS=-lecc -lmhash

all: eccvpn

eccvpn: eccvpn.o rscode/libecc.a

eccvpn.o: eccvpn.c eccvpn.h

clean:
	rm -f core* *~ *.o eccvpn
	$(MAKE) -C rscode clean

rscode/libecc.a:
	$(MAKE) -C rscode

