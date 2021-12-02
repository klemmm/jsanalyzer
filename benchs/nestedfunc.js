function foo(x) {
	var bar = function(y) {
		console.log(y);
	} 
	bar(x);
}

v = foo(42);
