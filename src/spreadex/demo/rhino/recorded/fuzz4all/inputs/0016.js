print(
  (function f(x) {
     
    var y = 0, s = Symbol("id");
    let z = 1;           
    const c = ++z + +false + `${z}${c}`;  
     
     

    function* g() {
      for (let i = 0n; i < 5n; i++) yield i + x;
    }

    let arr = [];
    for (let v of g()) arr.push(v + (typeof s === "symbol"));
     

    return y + z + arr.length + +true + arr.reduce((a,b)=>a+(+b),0);
  })(10)
);
