function* fibGen(n) {
  var a = 0n, b = 1n;  
  for (var i = 0; i < n; i++) {
    yield a;
    a = b;
    b = a + b;  
  }
}
const SYM = Symbol('key');
var fibObj = {};  

try {
  let count = 12;  
  for (let num of fibGen(count)) {
     
    fibObj[SYM.toString() + ':' + num.toString(10)] = num + ''; 
     
    if (typeof num === 'bigint' && +num > 8 && +num % 2 === 0) throw new Error('EvenBigNum:' + num);
  }
} catch (e) {
  console.log('Caught error:', e.message || e);
}

 
var keys = [];
for (var k in fibObj) keys.push(k);
for (var j = keys.length - 1; j >= 0; j--) {
  console.log(keys[j] + ' => ' + fibObj[keys[j]]);
}

 
const x = 1;
var x = 2;   
console.log('x =', x);
