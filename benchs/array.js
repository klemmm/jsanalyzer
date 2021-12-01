a = [0,1,2];
if (Math.random(1)) {
	a[0] = 5;
} else {
	a[5] =5;
}

b = [[0,1],[2,3]];

x = b[1][1] + a[2];

function plip() {
	var a = [1];
	a[0] = 42;
	return a;

}

u = plip();
v = plip();

u[0] = u[0] + 1;

blop = [];
blop["blu"] = 51;

p = blop.blu;

blop.blu = 52;

z = blop["blu"];
