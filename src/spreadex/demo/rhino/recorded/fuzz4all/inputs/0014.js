print("Start");

 
print("foo before =", typeof foo);
var foo = 123n + 7n;  

 
{
  let x = 10;
  const x = 20;  

   
   

  print("x in block =", x);
}
print("foo after =", foo);

 
var sym = Symbol("id");
var obj = {};
obj[sym] = "symbol value";
obj["id"] = "string key";

print("obj[sym] =", obj[sym]);
print("obj['id'] =", obj["id"]);

 
function* gen(n) {
  var s = 0n;
  for (var i = 0n; i < n; i += 1n) {
    yield i;
    s += i;
  }
  return s;
}

var it = gen(5n);
var sum = 0n;
while (true) {
  var res = it.next();
  if (res.done) break;
  print("gen yields:", res.value);
  sum += res.value;
}
print("sum of yielded =", sum);
print("returned total =", res.value);
