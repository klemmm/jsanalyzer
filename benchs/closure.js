function maker() {
	var x;
	function closure() {
		x = x + 1;
		return x;
	} 
	x = 42;
	return closure;
}

f = maker();
x = f();
console.log(x);
x = f();
console.log(x);
