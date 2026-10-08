const sym = Symbol('id');
var obj = {};
{
  let sym2 = Symbol('inner');
  obj[sym2] = 42n ** 3n;       
}
obj[sym] = 1/0 + 'px';        

 
function* gen() {
  yield null;
  yield true && sym;           
  yield obj[sym];              
  for (const v of [1, 2n, '3']) {
    try {
       
      let val = typeof v === 'number' ? BigInt(v) : v;
      yield val + 1n;          
    } catch(e) {
      yield 'error';
    }
  }
}

 
 

 
for (const v of gen()) {
  console.log(typeof v + ':', v);
}

 
console.log('hoistedVar:', hoistedVar);
var hoistedVar = 'now initialized';
console.log('hoistedVar after init:', hoistedVar);
