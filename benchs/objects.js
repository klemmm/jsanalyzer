a = [51];
a.f = function() {
	return 42;
}

function foo() {
	return 51;
}
x = a.f();
y = foo();
console.log(x);
