CFLAGS=-Iduktape -fPIC -O3 -march=native -W
LDLIBS=-lm
LDFLAGS=-shared

all: jseval.so escodegen_setup

jseval.so: jseval.o duktape/duktape.o
	$(CC) -o $@ $^ $(LDFLAGS) $(LDLIBS)

jseval.o: jseval.c duktape/duktape.h duktape/duk_config.h

escodegen_setup:
	npm install escodegen

clean:
	rm -f *~ jseval.so *.o duktape/*.o

.PHONY: all clean

