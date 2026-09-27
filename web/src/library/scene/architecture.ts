import * as THREE from "three";

// Visual reconstruction from three supplied views. All dimensions are relative.
export function buildLibraryArchitecture(parent: THREE.Group) {
  const B = new THREE.BoxGeometry(1, 1, 1);
  const pattern=(kind:"brick"|"roof")=>{
    const canvas=document.createElement("canvas");canvas.width=512;canvas.height=512;
    const c=canvas.getContext("2d")!;
    c.fillStyle=kind==="brick"?"#c8a995":"#ad6d5e";c.fillRect(0,0,512,512);
    if(kind==="brick"){
      for(let row=0;row<18;row++)for(let col=-1;col<13;col++){
        const offset=(row%2)*22;
        const tone=((row*17+col*11)%7)-3;
        c.fillStyle=`rgb(${183+tone*2},${108+tone},${87+tone})`;
        c.fillRect(col*44+offset+2,row*29+2,40,25);
      }
    }else{
      for(let row=0;row<22;row++){
        c.fillStyle=row%2?"#b47665":"#c28470";c.fillRect(0,row*24,512,22);
        c.fillStyle="#996459";c.fillRect(0,row*24+21,512,2);
        for(let col=0;col<16;col++){c.fillStyle="#a46d5f";c.fillRect(col*35+(row%2)*17,row*24,1,22)}
      }
    }
    const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;texture.anisotropy=4;return texture;
  };
  const brick = new THREE.MeshStandardMaterial({ map:pattern("brick"), roughness: .92 });
  const brickShade = new THREE.MeshStandardMaterial({ map:brick.map, color:0xd6c1b4, roughness: .94 });
  const pale = new THREE.MeshStandardMaterial({ color: 0xe6ddc6, roughness: .83 });
  const trim = new THREE.MeshStandardMaterial({ color: 0xc9bda4, roughness: .88 });
  const roofMat = new THREE.MeshStandardMaterial({ map:pattern("roof"), roughness: .85, side: THREE.DoubleSide });
  const roofDark = new THREE.MeshStandardMaterial({ color: 0x9b6255, roughness: .86 });
  const glass = new THREE.MeshStandardMaterial({ color: 0x496976, metalness: .28, roughness: .2 });
  const glassLit = new THREE.MeshStandardMaterial({ color: 0x89a8a8, metalness: .14, roughness: .23, transparent: true, opacity: .83 });
  const frame = new THREE.MeshStandardMaterial({ color: 0xe9e2d2, roughness: .63 });
  const steel = new THREE.MeshStandardMaterial({ color: 0x83918d, metalness: .55, roughness: .38 });
  const stone = new THREE.MeshStandardMaterial({ color: 0xc6c3b4, roughness: .92 });
  const paving = new THREE.MeshStandardMaterial({ color: 0xb1b5aa, roughness: .98 });
  const pavingAlt = new THREE.MeshStandardMaterial({ color: 0xa1a89d, roughness: .98 });
  const lawn = new THREE.MeshStandardMaterial({ color: 0x466a4a, roughness: 1 });
  const water = new THREE.MeshStandardMaterial({ color: 0x5e8a8f, metalness: .36, roughness: .16, transparent: true, opacity: .9 });
  const treeLeaf = [0x365d3d, 0x466b42, 0x55774a, 0x3e6048].map(color => new THREE.MeshStandardMaterial({color,roughness:1}));
  const bark = new THREE.MeshStandardMaterial({color:0x6b5a46,roughness:1});
  const solid=(w:number,h:number,d:number,x:number,y:number,z:number,m:THREE.Material,shadow=true)=>{
    const o=new THREE.Mesh(B,m);o.scale.set(w,h,d);o.position.set(x,y,z);o.castShadow=shadow;o.receiveShadow=true;parent.add(o);return o;
  };
  const cylinder=(r:number,h:number,x:number,y:number,z:number,m:THREE.Material,segments=20)=>{
    const o=new THREE.Mesh(new THREE.CylinderGeometry(r,r,h,segments),m);o.position.set(x,y,z);o.castShadow=true;parent.add(o);return o;
  };
  const roof=(w:number,d:number,x:number,y:number,z:number,rise:number,m:THREE.Material)=>{
    const hw=w/2,hd=d/2, ridge=Math.max(.05,Math.min(hw*.42,hd*.42));
    const v=[
      [-hw,0,-hd],[hw,0,-hd],[hw,0,hd],[-hw,0,hd],
      [-hw+ridge,rise,0],[hw-ridge,rise,0],
    ];
    const faces=[[0,1,5],[0,5,4],[3,4,5],[3,5,2],[0,4,3],[1,2,5]];
    const pts:number[]=[],uvs:number[]=[];
    faces.forEach(f=>f.forEach(i=>{pts.push(...v[i]);uvs.push(v[i][0]/w+.5,v[i][2]/d+.5)}));
    const g=new THREE.BufferGeometry();g.setAttribute("position",new THREE.Float32BufferAttribute(pts,3));g.setAttribute("uv",new THREE.Float32BufferAttribute(uvs,2));g.computeVertexNormals();
    const o=new THREE.Mesh(g,m);o.position.set(x,y,z);o.castShadow=true;o.receiveShadow=true;parent.add(o);
    solid(w+.25,.17,d+.25,x,y-.04,z,trim);
    solid(w-2*ridge,.1,.18,x,y+rise,z,roofDark);
  };
  const win=(x:number,y:number,z:number,w=.65,h=1.75,front=true)=>{
    const depth=front?.105:.09;
    solid(w+.22,h+.22,depth,x,y,z,frame,false);
    solid(w,h,.025,x,y,z+.07,glass,false);
    solid(.055,h,.04,x,y,z+.092,frame,false);
    solid(w,.06,.04,x,y+.12,z+.092,frame,false);
    solid(w+.29,.11,.18,x,y-h/2-.08,z+.06,trim,false);
    solid(w+.27,.1,.16,x,y+h/2+.1,z+.06,trim,false);
  };
  const sideWin=(x:number,y:number,z:number,w=.54,h=1.4)=>{
    solid(.13,h+.18,w+.16,x,y,z,frame,false);
    solid(.025,h,w,x+.077,y,z,glass,false);
    solid(.03,h,.045,x+.097,y,z,frame,false);
    solid(.19,.12,w+.27,x,y-h/2-.09,z,trim,false);
  };
  const arch=(x:number,bottom:number,z:number,w:number,h:number)=>{
    solid(w-.16,h-.16,.04,x,bottom+h/2,z,glass,false);
    const outer=new THREE.Shape();
    const r=w/2;
    outer.moveTo(-r,0);outer.lineTo(r,0);outer.lineTo(r,h-r);
    outer.absarc(0,h-r,r,0,Math.PI,false);
    outer.lineTo(-r,0);
    const inner=new THREE.Path();const ri=r-.15;
    inner.moveTo(-ri,.12);inner.lineTo(ri,.12);inner.lineTo(ri,h-r);
    inner.absarc(0,h-r,ri,0,Math.PI,false);inner.lineTo(-ri,.12);
    outer.holes.push(inner);
    const surround=new THREE.Mesh(new THREE.ShapeGeometry(outer,24),pale);
    surround.position.set(x,bottom,z+.08);parent.add(surround);
    solid(w+.22,.12,.16,x,bottom-.04,z+.1,trim,false);
  };
  const col=(x:number,y:number,z:number,h:number,r=.16)=>{
    cylinder(r,h,x,y,z,pale,24);
    solid(r*3,.21,r*3,x,y+h/2-.04,z,trim);
    solid(r*3.3,.22,r*3.3,x,y-h/2+.05,z,stone);
  };
  const rib=(points:THREE.Vector3[],radius:number,material:THREE.Material)=>{
    const curve=new THREE.CatmullRomCurve3(points);
    const mesh=new THREE.Mesh(new THREE.TubeGeometry(curve,36,radius,6,false),material);mesh.castShadow=false;parent.add(mesh);
  };
  const tree=(x:number,z:number,scale:number,seed:number)=>{
    cylinder(.11*scale,1.35*scale,x,.68*scale,z,bark,8);
      const leaf=treeLeaf[seed%treeLeaf.length];
    for(let j=0;j<4;j++){
      const a=j*2.399+seed;const crown=new THREE.Mesh(new THREE.SphereGeometry((.66+(j%2)*.15)*scale,12,9),leaf);
      crown.position.set(x+Math.cos(a)*.34*scale,(1.65+(j%3)*.22)*scale,z+Math.sin(a)*.3*scale);
      crown.castShadow=true;parent.add(crown);
    }
  };

  // Ground plan: central hall, two enclosing wings, corner towers and axial plaza.
  solid(90,.25,90,0,-.18,6,lawn,false);
  solid(53,.12,55,0,-.035,17,paving,false);
  solid(35,.2,17,0,.03,25,pavingAlt,false);
  for(let i=0;i<17;i++) solid(.035,.009,17,0,.105,15+i*1.16,stone,false);

  // Central atrium: brick podium under a continuous pale-glass clerestory.
  solid(14,7.5,17,0,3.85,-6,brick);
  solid(15,.38,18,0,7.7,-6,pale);
  solid(14.7,4.2,16.6,0,9.95,-6,frame);
  for(let x=-6.55;x<=6.6;x+=1.42){
    for(const y of [8.85,10.8]){
      win(x,y,2.36,.99,1.53);
      win(x,y,-14.37,.99,1.53);
    }
  }
  for(let z=-12.7;z<=.8;z+=1.5){
    sideWin(7.4,9.55,z,.9,2.65);
    sideWin(-7.4,9.55,z,.9,2.65);
  }
  solid(15.4,.34,17.4,0,12.12,-6,pale);
  solid(14.9,.16,17,0,12.32,-6,trim);

  // Glass dome and its steel meridians, photographed above the flat central roof.
  const dome=new THREE.Mesh(
    new THREE.SphereGeometry(2.7,48,24,0,Math.PI*2,0,Math.PI/2),
    new THREE.MeshStandardMaterial({color:0x89aab4,metalness:.28,roughness:.12,transparent:true,opacity:.84,side:THREE.DoubleSide})
  );
  dome.position.set(0,12.56,-6.5);dome.castShadow=true;parent.add(dome);
  cylinder(2.77,.38,0,12.49,-6.5,pale,48);
  cylinder(2.47,.26,0,12.78,-6.5,glass,48);
  for(let i=0;i<20;i++){
    const a=i*Math.PI/10;
    const p:THREE.Vector3[]=[];
    for(let j=0;j<=12;j++){
      const t=(j/12)*(Math.PI/2);
      p.push(new THREE.Vector3(Math.sin(t)*2.73*Math.cos(a),12.59+Math.cos(t)*2.73,-6.5+Math.sin(t)*2.73*Math.sin(a)));
    }
    rib(p,.018,steel);
  }
  for(const h of [.9,1.8]){
    const rr=Math.sqrt(2.7*2.7-h*h);
    const ring=new THREE.Mesh(new THREE.TorusGeometry(rr,.022,5,72),steel);
    ring.rotation.x=Math.PI/2;ring.position.set(0,12.59+h,-6.5);parent.add(ring);
  }

  // Foreground corner wings and rear arms create the U-shaped mass visible in aerial photos.
  for(const side of [-1,1]){
    const x=side*12.1;
    solid(10.2,7.6,8.8,x,3.9,2,brick);
    solid(10.65,.25,9.25,x,7.83,2,pale);
    roof(10.7,9.25,x,8.16,2,1.45,roofMat);
    // Rear arm is deliberately set behind the front wing, leaving a courtyard.
    solid(7.1,7.65,17,side*13.8,3.9,-10.2,brickShade);
    solid(7.45,.21,17.4,side*13.8,7.85,-10.2,pale);
    roof(7.5,17.5,side*13.8,8.16,-10.2,1.28,roofMat);
    for(let k=0;k<8;k++){
      const wx=side*(8.05+k*1.12);
      for(const yy of [2.1,4.7])win(wx,yy,6.47,.56,1.52);
      win(wx,6.87,6.47,.43,.58);
    }
    for(let k=0;k<7;k++){
      const zz=-2.5-k*2.1;
      for(const yy of [2.2,4.7])sideWin(side*17.4,yy,zz,.55,1.42);
      sideWin(side*10.2,4.7,zz,.55,1.42);
    }
    // Cream string courses, brick pilasters and parapet shadows.
    for(const y of [1.05,3.45,6.25]){
      solid(10.5,.13,.3,x,y,6.52,trim,false);
      solid(.2,.12,17.4,side*17.45,y,-10.2,trim,false);
    }
    for(let k=0;k<9;k++)solid(.15,6.45,.25,side*(7.45+k*1.17),4.18,6.53,brickShade,false);
    for(let k=0;k<12;k++)solid(.78,.08,.2,side*(7.6+k*.78),7.9,6.56,pale,false);

    // Outer towers: slender brick shaft, pale vertical bay, open arched belfry.
    const tx=side*18.7, tz=4.1;
    solid(3.1,10.7,3.25,tx,5.5,tz,brick);
    solid(3.45,.3,3.55,tx,10.94,tz,pale);
    solid(3.2,2.6,3.2,tx,12.4,tz,brick);
    solid(3.55,.24,3.55,tx,13.78,tz,pale);
    roof(3.7,3.7,tx,14,tz,.42,roofMat);
    solid(1.12,9.6,.09,tx,5.4,5.77,frame,false);
    for(const yy of [2.35,4.5,6.6,8.75])win(tx,yy,5.88,.74,1.5);
    arch(tx,11.7,5.87,1.12,1.55);
    arch(tx+side*1.66,11.7,4.1,1.1,1.55);
    for(const yy of [2.5,5.1,8.25])sideWin(tx+side*1.58,yy,4.05,.7,1.6);
    for(const y of [1.08,10.76,13.64])solid(3.55,.13,3.6,tx,y,tz,trim,false);
    // Side loggias and glazed connectors.
    solid(2.8,3.6,5.7,side*7.2,2.05,-2.6,brick);
    solid(2.6,2.35,.09,side*7.2,3.1,.3,glassLit,false);
    for(let c=0;c<3;c++)col(side*(6.25+c*.92),1.75,.56,2.8,.12);
  }

  // Broad glazed center entrance with rectilinear canopy and a real depth recess.
  solid(12,5,.6,0,2.9,2.62,frame);
  solid(10.8,4.25,.08,0,2.67,2.99,glass);
  for(let i=-5;i<=5;i++)solid(.08,4.4,.18,i*1.04,2.65,3.08,pale,false);
  for(const y of [1.6,3.7])solid(11,.08,.17,0,y,3.09,pale,false);
  solid(5,3.45,.1,0,2.17,3.13,glass);
  solid(5.55,.25,4.6,0,5.38,4.43,pale);
  for(const x of [-5.12,-3.07,-1.02,1.02,3.07,5.12])col(x,2.72,5.45,4.95,.2);
  solid(12.6,.28,3.7,0,5.38,5.22,trim);
  solid(13.5,.3,4.9,0,.51,5.65,stone);
  for(let i=0;i<9;i++)solid(14.1-i*.32,.12,.66,0,.06+i*.09,11.03-i*.56,stone,false);
  for(const side of [-1,1])solid(.19,.3,7,side*6.98,.79,8.55,frame,false);

  // Plaza pools and circular fountain basins, retaining the photograph's long axis.
  for(const [z,d] of [[17.2,6.8],[25.4,6.5],[32.3,4.4]]){
    solid(14,.25,d,0,.1,z,stone,false);
    solid(13.3,.035,d-.65,0,.25,z,water,false);
    const ring=new THREE.Mesh(new THREE.TorusGeometry(.72,.11,8,32),stone);
    ring.rotation.x=Math.PI/2;ring.position.set(0,.35,z);parent.add(ring);
  }
  for(const side of [-1,1]){
    // Small freestanding reading pavilions flanking the plaza.
    solid(5.3,2.55,4.6,side*23,1.45,20.5,brick);
    roof(5.8,5.1,side*23,2.88,20.5,.45,roofMat);
    for(const q of [-1,0,1])win(side*23+q*1.4,1.7,22.84,.79,1.5);
  }
  // Rows of planting, varied crowns and scale avoid a repeated low-poly hedge.
  for(const side of [-1,1]){
    for(let i=0;i<10;i++)tree(side*(10.5+(i%2)*1.2),13+i*2.7,.83+(i%3)*.12,i+Math.max(0,side));
    for(let i=0;i<11;i++)tree(side*(21+i%3*2.8),-14+i*4.4,1.5+(i%4)*.16,i+4);
  }
}
