function* fibGen(n) {
  var a = 0n, b = 1n;
  var i = 0;
  while(i < n) {
    yield a;
    var temp = a + b;
    a = b;
    b = temp;
    i++;
  }
}
var SYM = Symbol('key');
var fibObj = {};
try {
  var count = 15;
  var it = fibGen(count);
  var res;
  while(!(res = it.next()).done) {
    var val = res.value;
    var key = SYM.toString() + ':' + val;
    fibObj[key] = val.toString();
    if(typeof val === 'bigint' && +val > 50) throw new Error('BigFibTooBig:' + val);
  }
} catch(e) {
  console.log('Caught:', e.message || e);
}
var keys = Object.keys(fibObj);
for(var i = 0; i < keys.length; i++) {
  console.log(keys[i] + ' -> ' + fibObj[keys[i]]);
}
