function* gen(n) {
  let s = Symbol('count'), sum = 0n;
  for (var i = 0n; i < n; i++) {
    yield i;
    sum += i;
  }
  return sum;
}

try {
  const x = 10;
   
  let {
    a = (function () {
      throw 'early exit ' + String(s);
    })()
  } = {};
} catch (e) {
  print('Caught:', e);
}

var it = gen(5n);
while (true) {
  var r = it.next();
  if (r.done) {
    print('Sum:', r.value.toString());
    break;
  }
  console.log('Yielded:', r.value.toString());
}
