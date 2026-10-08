function* fibGen(n) {
  var a = 0n, b = 1n;
  for (var i = 0; i < n; i++) {
    yield a;
    var sum = a + b;
    a = b;
    b = sum;
  }
}
const SYM = Symbol('key');
const fibObj = Object.create(null);
try {
  var count = 15;
  for (var num of fibGen(count)) {
     
    fibObj[String(SYM) + (num + '')] = num.toString();
    if (typeof num === 'bigint' && Number(num) > 30) throw new Error('BigFibTooBig:' + num);
  }
} catch (e) {
  console.log('Caught:', e.message || e);
}
(() => {
   
  var syms = Object.getOwnPropertySymbols(fibObj);
  for (var i = 0; i < syms.length; i++) {
    console.log(syms[i].toString() + ' -> ' + fibObj[syms[i]]);
  }
  for (var k in fibObj) {
    if (fibObj.hasOwnProperty(k)) console.log(k + ' -> ' + fibObj[k]);
  }
})();
