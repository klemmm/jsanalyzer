function foo(x) {
	var cl = 123;
	console.log("titu");
	var bar = function (y) {
		console.log(y);
	} 
	console.log("totito");
	bar(x);
}

v = foo(42);
