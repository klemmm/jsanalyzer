someApiObject1 = undefined
someApiObject2 = undefined

g = 10;

function outerFn1() {

	var x = 51;
	var c = 0;

	someApiObject1 = {}
	someApiObject1.y = 42;

	someApiObject1.onevent = function() {
		foo(x, this.y, c, g); /* x et this.y vont etre constants, mais pas c ni g */
		c = 1;
	}
}

function outerFn2() {

	var x = 151;
	var c = 0;

	someApiObject2 = {}
	someApiObject2.y = 142;

	someApiObject2.onevent = function() {
		foo(x, this.y, c, g); /* pareil que pour la premiere fonction */
		c = 1;
		g = 20;
	}
}


if (random) {
	outerFn1();
}
if (random) {
	outerFn2();
}

/* appel des callbacks, la je l'ai fait explicitement mais ca devra etre simulé par l'analyseur */

while(1) { /* on appelle les callbacks en boucle dans un ordre random jusqu'a ce que l'état abstrait se stabilise */
	if (random) { someApiObject1.onevent(); }
	if (random) { someApiObject2.onevent(); }
}
