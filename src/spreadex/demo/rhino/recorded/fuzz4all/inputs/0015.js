print("Start");

var x = 1;
function f() { x = 2; var x; return x; }  
console.log("f() returns:", f(), "global x:", x);

{
  let y = 3;
   
   
  const y = 4;   
   
  console.log("block y (let):", y);
}
try {
  console.log("outside block y:", y);
} catch(e) {
  console.log("outside block y throws:", e);
}
console.log("global y (const):", y);

var sym = Symbol("id"), big = 1n;
function* gen() {
  yield sym;
  yield big;
  yield* [7, 8];
}
var g = gen();

print("Generator outputs:");
for (var v of g) {
  print(" -", typeof v, v.toString ? v.toString() : v);
}

print("BigInt and Number mixed arithmetic:");
var n = 10;
try {
  print(big + n);     
} catch(e) {
  print("error mixing BigInt and number:", e);
}
print("BigInt + BigInt:", big + 2n);

print("Done");
