import * as THREE from "three";

/** 展厅灯光（2026-10-01 从 LibraryScene 抽出）：外景/内景两档。
    依赖场景与模式；行为与拆分前一致。 */
export function setupLibraryLights(
  scene: THREE.Scene,
  mode: "exterior" | "room",
) {
    /* =======================================================
       Lights
    ======================================================= */

    const hemi =
      new THREE.HemisphereLight(

        mode === "exterior"
          ? 0xe3eef3
          : 0xf1e2c8,

        mode === "exterior"
          ? 0x453b32
          : 0x2f2b27,

        mode === "exterior"
          ? 2.6
          : 0.58

      );


    scene.add(
      hemi
    );


    const sun =
      new THREE.DirectionalLight(

        0xffe7bb,

        mode === "exterior"
          ? 3.4
          : 0.82

      );


    sun.position.set(

      mode === "exterior"
        ? -22
        : -12,

      mode === "exterior"
        ? 34
        : 24,

      mode === "exterior"
        ? 29
        : 15

    );


    sun.castShadow =
      true;


    sun.shadow.mapSize.set(
      2048,
      2048
    );


    sun.shadow.camera.left =
      -55;

    sun.shadow.camera.right =
      55;

    sun.shadow.camera.top =
      55;

    sun.shadow.camera.bottom =
      -55;

    sun.shadow.bias =
      -0.00025;

    sun.shadow.normalBias =
      0.035;

    if (mode === "room") {
      sun.target.position.set(
        0,
        3.2,
        0
      );
      scene.add(
        sun.target
      );
    }


    scene.add(
      sun
    );


    /* =======================================================
       V6.3 室内灯光层次

       1. 顶部自然光：负责大厅整体空气感
       2. 暖色反射光：负责木材和中央展台
       3. 三盏柔和聚光：只强化中央馆藏，不做舞台感
    ======================================================= */

    if (
      mode === "room"
    ) {

      const ambientFill =
        new THREE.AmbientLight(
          0xffedcf,
          0.05
        );

      scene.add(
        ambientFill
      );


      const domeLight =
        new THREE.PointLight(

          0xe5f3ff,

          5.0,

          44,

          2

        );


      domeLight.position.set(
        0,
        18,
        1.5
      );


      scene.add(
        domeLight
      );


      const warmLight =
        new THREE.PointLight(

          0xffd0a0,

          2.4,

          20,

          2

        );


      warmLight.position.set(
        0,
        3.1,
        1.0
      );


      scene.add(
        warmLight
      );


      const centralTarget =
        new THREE.Object3D();

      centralTarget.position.set(
        0,
        0.9,
        0
      );

      scene.add(
        centralTarget
      );


      const exhibitLights = [
        {
          position: new THREE.Vector3(-5.6, 8.4, 5.0),
          intensity: 4.8,
          color: 0xffd2a3,
        },
        {
          position: new THREE.Vector3(5.4, 8.0, 4.4),
          intensity: 4.2,
          color: 0xffdfb8,
        },
        {
          position: new THREE.Vector3(0.0, 9.0, -6.4),
          intensity: 3.4,
          color: 0xffe9cf,
        },
      ];

      exhibitLights.forEach(
        ({
          position,
          intensity,
          color,
        }) => {
          const spot =
            new THREE.SpotLight(
              color,
              intensity,
              24,
              Math.PI / 5.8,
              0.82,
              2
            );

          spot.position.copy(
            position
          );

          spot.target =
            centralTarget;

          spot.castShadow =
            false;

          scene.add(
            spot
          );
        }
      );

    }


}
