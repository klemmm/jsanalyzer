var toto;
toto = "blabla";

blibli = toto + "tutu";


plop = function() {
	var c = 1;
	d = 10;
	e = 42;
	if (Math.random(0.5)) {
		d = 2;
		f = 5;
		return "lilili";
	} else {
		d = 3;
		f = 5;
		return "lilili";
	}
	f = 6;
}

p = plop();
console.log(p);

