import {Canvas,useFrame} from "@react-three/fiber";
import {useRef} from "react";
import type {Group,Mesh} from "three";

export function VoiceCore3D({reducedMotion=false}:{reducedMotion?:boolean}){
  return <div className="voice-core-canvas" aria-hidden="true">
    <Canvas
      dpr={[1,1.5]}
      frameloop={reducedMotion?"demand":"always"}
      camera={{position:[0,0,4.8],fov:34}}
      gl={{alpha:true,antialias:true,powerPreference:"high-performance"}}
      fallback={<div className="voice-core-fallback"/>}
    >
      <ambientLight intensity={0.65}/>
      <pointLight color="#8b7cff" intensity={22} position={[-2.4,1.8,2.2]}/>
      <pointLight color="#ffb86b" intensity={18} position={[2.8,-1.3,2]}/>
      <pointLight color="#45d6e8" intensity={10} position={[0,2.8,-1]}/>
      <VoiceCore reducedMotion={reducedMotion}/>
    </Canvas>
  </div>;
}

function VoiceCore({reducedMotion}:{reducedMotion:boolean}){
  const assembly=useRef<Group>(null);
  const heart=useRef<Mesh>(null);

  useFrame((state,delta)=>{
    if(reducedMotion)return;
    if(assembly.current){
      assembly.current.rotation.y+=delta*.11;
      assembly.current.rotation.x=Math.sin(state.clock.elapsedTime*.24)*.1;
    }
    if(heart.current){
      const pulse=1+Math.sin(state.clock.elapsedTime*1.7)*.025;
      heart.current.scale.setScalar(pulse);
    }
  });

  return <group ref={assembly} rotation={[.18,-.35,0]}>
    <mesh ref={heart}>
      <icosahedronGeometry args={[.72,5]}/>
      <meshPhysicalMaterial
        color="#7768f6"
        emissive="#392b98"
        emissiveIntensity={1.25}
        metalness={.22}
        roughness={.24}
        clearcoat={1}
        clearcoatRoughness={.18}
      />
    </mesh>
    <mesh scale={1.16}>
      <icosahedronGeometry args={[.72,3]}/>
      <meshBasicMaterial color="#b5adff" transparent opacity={.075} wireframe/>
    </mesh>
    <Ring rotation={[Math.PI/2,0,0]} color="#8b7cff" radius={1.42}/>
    <Ring rotation={[Math.PI/2,.72,.28]} color="#ffb86b" radius={1.67}/>
    <Ring rotation={[.35,-.3,Math.PI/2]} color="#45d6e8" radius={1.9} faint/>
    <mesh position={[0,0,-.6]}>
      <circleGeometry args={[2.45,96]}/>
      <meshBasicMaterial color="#8b7cff" transparent opacity={.025}/>
    </mesh>
  </group>;
}

function Ring({rotation,color,radius,faint=false}:{rotation:[number,number,number];color:string;radius:number;faint?:boolean}){
  return <mesh rotation={rotation}>
    <torusGeometry args={[radius,.018,12,180]}/>
    <meshBasicMaterial color={color} transparent opacity={faint ? .32 : .72}/>
  </mesh>;
}
