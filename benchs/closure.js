function maker() {
	var x = 42;
	function closure() {
		x = x + 1;
		return x;
	}
	return closure;
}

f = maker();
x = f();
console.log(x);
x = f();
console.log(x);
