const sym = Symbol('id');

function* gen(n) {
  let x = 0n;
  while (x < n) {
    yield x;
    x += 1n;
  }
}

let result = '';
for (const v of gen(5n)) {
   
  const vStr = String(v) + (v === 2n ? '!' : '');
  result += vStr;
}

var let = 'shadowing var by let causes SyntaxError in same block';  
 
{
  let let = 'block let works';
  print(let);  
}

var re = /(\d+)/g;
var str = 'x1y2z3';
var matches = [];
console.log(
   
  [...str.matchAll(re)]
    .map(m => m[1] + sym.description)
    .join(',')
);

print('Result:' + result);
