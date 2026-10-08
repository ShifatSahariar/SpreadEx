function* fib(n) {
  var a = 0n, b = 1n, i = 0;
  while (i++ < n) yield a, [a, b] = [b, a + b];  
}

print("Fib(5):");
for (let x of fib(5)) {
  print(x + "n");
}

 
var obj = {};
var s = Symbol("id");
obj[s] = "symbolic";

{
  let s = "shadowed";
  print("Inside block s:", s);
}
print("Outside block obj[s]:", obj[s]);

 
const x = 1;
const x = 2;  

print("const redeclared x:", x);

 
try {
  throw "simple string error";
} catch (e) {
  print("Caught:", e);
}

 
hoisted();
function hoisted() {
  print("Hoisted function runs fine");
}
