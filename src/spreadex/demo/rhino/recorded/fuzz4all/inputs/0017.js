(function* gen() {
    let sym = Symbol("x"), [a,b]=[1n, Number(2n)], c = (a+b) + "" + String(sym), d;
    try {
        d = yield c.includes("Symbol") ? c : (function f(x){return x<=0?0:f(x-1)+x})(5);
    } catch(e) {
        d = "error:"+e;
    }
    return d + " " + typeof sym + " " + ({}+[]);
})()
.next()
.value && print("Result:", 
  (function(){
    let x = 10, y = 20;
     
    {let x=30; y+=x;}
    return x + y;  
  })()
);
