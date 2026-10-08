print(f());  

 
{
  let x = 1;
  const x = 2;  
  print(x);     

   
}

print(x);  

 
var big = 10n, num = 32;
print(big + 20n);         
print(Number(big) + num);  

 
function* fib() {
  var a = 0, b = 1, i = 0;
  while(i++ < 5)
    yield a, [a, a = b, b = a + b][0];
}

 
var sum=0;
for (var n of fib()) sum+=n;
print(sum);  

 
var sq = x => x*x;
print(sq(6));
