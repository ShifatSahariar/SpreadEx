const S = Symbol('desc'), N = 10n, arr = [1,2,3], obj = {};
var x = 5;

function* gen(n) {
  var i = 0;
  while(i < n){
    i++;
     
    yield i * N;
  }
}

 
{
  let y = 10;
   
  console.log('y:', y);
}

obj[S] = 'symbolic prop';

for(var v of gen(3)){
  print('gen yields:', v.toString() + ', sum+v:', (x + Number(v)) );
}

 
print('before var x:', x, 'typeof S:', typeof S, 'arr map:', arr.map(function(e){ return e*x; }));

 
const c = 1;
print('const c initial:', c);
const c = 2;  
print('const c redeclared:', c);
