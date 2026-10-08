print(
   
  (function* gen() {
     
    let s = Symbol('id'), n = 1n, r = 0;
    const c = { a: 1, [s]: 2 };
    var x = 0;
    while (x < 5) {
       
      r += Number(n + BigInt(x));
      x++;
    }
    yield r + c.a + c[s];
    yield* [1, 2, 3];
  })()
   
);
var res = [];
var g = (function* gen() {
  let s = Symbol('id'), n = 1n, r = 0;
  const c = { a: 1, [s]: 2 };
  var x = 0;
  while (x < 5) {
    r += Number(n + BigInt(x));
    x++;
  }
  yield r + c.a + c[s];
  yield* [1, 2, 3];
})();
var v;
while (!(v = g.next()).done) res.push(v.value);
console.log(res);
