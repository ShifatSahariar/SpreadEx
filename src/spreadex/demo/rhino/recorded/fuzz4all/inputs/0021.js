print('Start');

 
console.log(foo());  

var x = 1;
function foo() {
   
  console.log(x);  
  let y = 10;
   
  const y = 20;  
  try {
    let y = 30;  
    console.log(y);  
  } catch(e) {
    print('Error: ' + e);
  }
  return y + x;  
}

 
var sym1 = Symbol('foo');
var o = {};
o[sym1] = 'symbolValue';
o['sym1'] = 'stringKeyValue';

 
function* gen(n) {
  let b = 0n;
  for (var i = 0; i < n; i++) {
    b += 1n;
    yield b;
  }
}

var g = gen(3);
for (var v of g) {
  console.log('Yielded BigInt: ' + v + ' type:' + typeof v);  
}

console.log('Object keys:', Object.keys(o));
console.log('Symbol key prop:', o[sym1]);
console.log('String key prop:', o['sym1']);

 
var n = 10;
var big = 20n;
console.log('BigInt + number as string:', big + '' + n);  

print('End');
