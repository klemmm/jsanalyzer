#include "duktape.h"

typedef enum {
	NUMBER = 0, 
	STRING = 1,
	UNDEFINED = 2,
	NUL = 3,
	BOOL = 4,
} jsctype_t;

typedef union {
	char *s;
	double n;
	int b;
} jscdata_u;

typedef struct {
	jsctype_t type;
	jscdata_u data;
} jscval_t;

static duk_context *ctx = NULL;


static jscval_t get_val(int idx) {
	jscval_t r;
	if (duk_is_number(ctx, -1)) {
		r.type = NUMBER;
		r.data.n = duk_get_number(ctx, -1);
	} else if (duk_is_string(ctx, -1)) {
		r.type = STRING;
		r.data.s = strdup(duk_get_string(ctx, -1));
	} else if (duk_is_undefined(ctx, -1)) {
		r.type = UNDEFINED;
	} else if (duk_is_null(ctx, -1)) {
		r.type = NUL;
	} else if (duk_is_boolean(ctx, -1)) {
		r.type = BOOL;
		r.data.b = duk_get_boolean(ctx, -1);
	} else {
		fprintf(stderr, "get_val: unhandled value");
		abort();
	}
	return r;
}

static void push_val(jscval_t val) {
	switch(val.type) {
		case NUMBER:
			duk_push_number(ctx, val.data.n);
			break;
		case STRING:
			duk_push_string(ctx, val.data.s);
			break;
		case NUL:
			duk_push_null(ctx);
			break;
		case UNDEFINED:
			duk_push_undefined(ctx);
			break;
		case BOOL:
			duk_push_boolean(ctx, val.data.b);
			break;
	}
}

void free_val(jscval_t r) {
	if (r.type == STRING) free(r.data.s);
}

jscval_t call_function(char *name, jscval_t *args, int nargs) {
	jscval_t r;
	int i;
	printf("call func %s with %d arg(s)\n", name, nargs);
	duk_get_global_string(ctx, name);
	for (i = 0; i < nargs; i++) {
		push_val(args[i]);
	}
	duk_call(ctx, nargs);
	r = get_val(-1);
	duk_pop(ctx);
	return r;
}

void register_function(char *def) {
	printf("register func: %s\n", def);
	duk_eval_string(ctx, def);
	duk_pop(ctx);
}

void initialize(void) {
	ctx = duk_create_heap_default();
}

