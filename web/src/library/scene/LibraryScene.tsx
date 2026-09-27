"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { buildLibraryArchitecture } from "./architecture";
import type { ShelfBookPreview } from "../types";


type Props = {
  books: ShelfBookPreview[];
  mode: "exterior" | "room";
  entering: boolean;
  motion: boolean;
  onPick: (index: number) => void;
  onTakeStart?: (index: number) => void;
  returnIssue?: number | null;
  onReturnComplete?: () => void;
  view: "front" | "aerial";
};


export function LibraryScene({
  books,
  mode,
  entering,
  motion,
  onPick,
  onTakeStart,
  returnIssue = null,
  onReturnComplete,
  view,
}: Props) {

  const host = useRef<HTMLDivElement>(null);

  const [fallback, setFallback] =
    useState(false);

  const pick =
    useRef(onPick);

  const takeStartRef =
    useRef(onTakeStart);

  const enteringRef =
    useRef(entering);

  const entryStart =
    useRef(0);

  const motionRef =
    useRef(motion);

  const returnCompleteRef =
    useRef(onReturnComplete);


  pick.current = onPick;
  takeStartRef.current = onTakeStart;
  returnCompleteRef.current = onReturnComplete;


  /* =========================================================
     entering 状态
  ========================================================= */

  useEffect(() => {

    if (
      entering &&
      !enteringRef.current
    ) {

      entryStart.current =
        performance.now();

    }

    enteringRef.current =
      entering;

  }, [entering]);


  useEffect(() => {

    motionRef.current =
      motion;

  }, [motion]);


  /* =========================================================
     场景主体
  ========================================================= */

  useEffect(() => {

    if (!host.current) return;


    const mount =
      host.current;


    let disposed =
      false;


    /* =======================================================
       环境
    ======================================================= */

    const scene =
      new THREE.Scene();


    scene.background =
      new THREE.Color(

        mode === "exterior"
          ? 0x779296
          : 0x2f3934

      );


    scene.fog =
      new THREE.FogExp2(

        mode === "exterior"
          ? 0x779296
          : 0x35413a,

        mode === "exterior"
          ? 0.006
          : 0.00038

      );


    /* =======================================================
       Camera

       以后如果只想调“室内中庭”的默认视角，
       只改下面 ROOM_CAMERA_* 这 3 组参数即可。
       外景参数完全独立，不会再混在一起。
    ======================================================= */

    const ROOM_CAMERA_FOV = 46;

    const ROOM_CAMERA_POSITION =
      new THREE.Vector3(
        2.8,
        2.15,
        11.8
      );

    const ROOM_CAMERA_TARGET =
      new THREE.Vector3(
        0,
        2.8,
        0
      );


    const camera =
      new THREE.PerspectiveCamera(

        mode === "exterior"
          ? 36
          : ROOM_CAMERA_FOV,

        1,

        0.1,

        220

      );


    /* -------------------------------------------------------
       外景：保留原来的视角
       室内：使用独立的 ROOM_CAMERA_POSITION / TARGET
    ------------------------------------------------------- */

    const origin =

      mode === "exterior"

        ? (
            view === "front"

              ? new THREE.Vector3(
                  0,
                  12,
                  47
                )

              : new THREE.Vector3(
                  31,
                  25,
                  43
                )
          )

        : ROOM_CAMERA_POSITION.clone();


    const target =

      mode === "exterior"

        ? new THREE.Vector3(
            0,
            5.8,
            2
          )

        : ROOM_CAMERA_TARGET.clone();


    camera.position.copy(
      origin
    );


    camera.lookAt(
      target
    );


    /* =======================================================
       Renderer
    ======================================================= */

    const canvas =
      document.createElement(
        "canvas"
      );


    let renderer:
      THREE.WebGLRenderer;


    try {

      const context =
        canvas.getContext(
          "webgl2",
          {
            antialias: true,
            alpha: false,
          }
        );


      if (!context) {

        setFallback(true);

        return;

      }


      renderer =
        new THREE.WebGLRenderer({

          canvas,

          context,

          antialias: true,

          alpha: false,

          powerPreference:
            "high-performance",

        });


      setFallback(false);

    }

    catch {

      setFallback(true);

      return;

    }


    renderer.setPixelRatio(

      Math.min(

        window.devicePixelRatio || 1,

        1.8

      )

    );


    renderer.outputColorSpace =
      THREE.SRGBColorSpace;


    renderer.toneMapping =
      THREE.ACESFilmicToneMapping;


    /*
      外景稍亮
      室内降低曝光
    */

    renderer.toneMappingExposure =

      mode === "exterior"

        ? 1.35

        : 0.78;


    renderer.shadowMap.enabled =
      true;


    renderer.shadowMap.type =
      THREE.PCFSoftShadowMap;


    /* =======================================================
       V6.3：室内 PBR 环境反射

       不更换 Blender 几何，只给木材、石材和玻璃一个
       更柔和的室内反射环境，避免材质“塑料平面感”。
    ======================================================= */

    let pmremGenerator:
      THREE.PMREMGenerator | null = null;

    let roomEnvironmentTexture:
      THREE.Texture | null = null;

    if (mode === "room") {

      pmremGenerator =
        new THREE.PMREMGenerator(
          renderer
        );

      pmremGenerator.compileEquirectangularShader();

      roomEnvironmentTexture =
        pmremGenerator.fromScene(
          new RoomEnvironment(),
          0.04
        ).texture;

      scene.environment =
        roomEnvironmentTexture;

    }


    mount.appendChild(
      renderer.domElement
    );

    if (
      mode === "room" &&
      returnIssue !== null
    ) {
      renderer.domElement.style.opacity =
        "0";
      renderer.domElement.style.transition =
        "opacity 180ms ease";
    }


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


    /* =======================================================
       Root Group
    ======================================================= */

    const group =
      new THREE.Group();


    scene.add(
      group
    );


    /* =======================================================
       一些辅助函数
    ======================================================= */

    /* =======================================================
       Canvas 封面纹理
    ======================================================= */

    const textTex = (

      lines: string[],

      _bg: string,

      _fg: string,

      width = 512,

      height = 640

    ) => {

      const cv =
        document.createElement(
          "canvas"
        );

      cv.width = width;
      cv.height = height;

      const ctx =
        cv.getContext("2d")!;

      const period =
        lines[2] || "";

      const issueText =
        lines[1] || "";

      /* -----------------------------------------------
         图3风格：深墨绿布纹 + 金色双线 + 校园线稿
      ----------------------------------------------- */

      const gradient =
        ctx.createLinearGradient(
          0,
          0,
          width,
          height
        );

      gradient.addColorStop(
        0,
        "#0d2f22"
      );

      gradient.addColorStop(
        0.52,
        "#173f2f"
      );

      gradient.addColorStop(
        1,
        "#0d2b20"
      );

      ctx.fillStyle = gradient;
      ctx.fillRect(
        0,
        0,
        width,
        height
      );

      /* 细密布纹 */
      ctx.save();
      ctx.globalAlpha = 0.055;
      ctx.strokeStyle =
        "#f0e4bd";
      ctx.lineWidth = 1;

      for (
        let y = 2;
        y < height;
        y += 5
      ) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y + 9);
        ctx.stroke();
      }

      ctx.restore();

      const gold =
        "#d8c58c";

      const mutedGold =
        "rgba(216,197,140,.66)";

      /* 双边框 */
      ctx.strokeStyle = gold;
      ctx.lineWidth = 4;
      ctx.strokeRect(
        18,
        18,
        width - 36,
        height - 36
      );

      ctx.strokeStyle =
        mutedGold;
      ctx.lineWidth = 1.5;
      ctx.strokeRect(
        28,
        28,
        width - 56,
        height - 56
      );

      ctx.textBaseline =
        "middle";

      /* 云南大学 */
      ctx.textAlign =
        "left";
      ctx.fillStyle = gold;
      ctx.font =
        "600 28px STKaiti, KaiTi, serif";
      ctx.fillText(
        "云南大学",
        58,
        72
      );

      ctx.font =
        "12px Georgia, serif";
      ctx.letterSpacing =
        "2px" as any;
      ctx.fillText(
        "YUNNAN UNIVERSITY",
        58,
        98
      );

      /* 主标题 */
      ctx.textAlign =
        "center";
      ctx.font =
        "600 55px STSong, SimSun, serif";
      ctx.fillText(
        "学科信息参考",
        width / 2,
        190
      );

      ctx.font =
        "14px Georgia, serif";
      ctx.fillText(
        "DISCIPLINARY INFORMATION REFERENCE",
        width / 2,
        228
      );

      /* 分隔线 */
      ctx.strokeStyle =
        mutedGold;
      ctx.lineWidth = 1.3;
      ctx.beginPath();
      ctx.moveTo(100, 262);
      ctx.lineTo(width / 2 - 18, 262);
      ctx.moveTo(width / 2 + 18, 262);
      ctx.lineTo(width - 100, 262);
      ctx.stroke();

      ctx.save();
      ctx.translate(
        width / 2,
        262
      );
      ctx.rotate(Math.PI / 4);
      ctx.strokeRect(
        -4,
        -4,
        8,
        8
      );
      ctx.restore();

      ctx.font =
        "600 29px Georgia, serif";
      ctx.fillText(
        period,
        width / 2,
        304
      );

      ctx.font =
        "19px STSong, SimSun, serif";
      ctx.fillText(
        issueText,
        width / 2,
        338
      );

      /* 云南大学建筑线稿（简化版） */
      ctx.save();
      ctx.strokeStyle =
        "rgba(216,197,140,.47)";
      ctx.lineWidth = 1.4;
      ctx.translate(
        0,
        24
      );

      const cx =
        width / 2;
      const by = 444;

      ctx.beginPath();
      ctx.moveTo(84, by + 64);
      ctx.lineTo(width - 84, by + 64);
      ctx.moveTo(112, by + 64);
      ctx.lineTo(140, by + 26);
      ctx.lineTo(cx - 72, by + 26);
      ctx.lineTo(cx - 58, by + 2);
      ctx.lineTo(cx + 58, by + 2);
      ctx.lineTo(cx + 72, by + 26);
      ctx.lineTo(width - 140, by + 26);
      ctx.lineTo(width - 112, by + 64);
      ctx.stroke();

      for (
        let i = -3;
        i <= 3;
        i++
      ) {
        const x =
          cx + i * 23;
        ctx.strokeRect(
          x - 7,
          by + 12,
          14,
          34
        );
      }

      for (
        let i = 0;
        i < 6;
        i++
      ) {
        const yy =
          by + 72 + i * 8;
        const half =
          48 + i * 12;
        ctx.beginPath();
        ctx.moveTo(
          cx - half,
          yy
        );
        ctx.lineTo(
          cx + half,
          yy
        );
        ctx.stroke();
      }

      ctx.restore();

      /* 校徽式圆章 */
      const sealY =
        height - 96;
      ctx.strokeStyle = gold;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(
        width / 2,
        sealY,
        44,
        0,
        Math.PI * 2
      );
      ctx.stroke();

      ctx.beginPath();
      ctx.arc(
        width / 2,
        sealY,
        35,
        0,
        Math.PI * 2
      );
      ctx.stroke();

      ctx.fillStyle = gold;
      ctx.font =
        "600 26px STSong, SimSun, serif";
      ctx.fillText(
        "雲",
        width / 2,
        sealY - 5
      );
      ctx.font =
        "10px Georgia, serif";
      ctx.fillText(
        "1923",
        width / 2,
        sealY + 20
      );

      ctx.font =
        "13px STSong, SimSun, serif";
      ctx.fillText(
        "会泽百家  至公天下",
        width / 2,
        height - 38
      );

      const texture =
        new THREE.CanvasTexture(
          cv
        );

      texture.colorSpace =
        THREE.SRGBColorSpace;

      texture.anisotropy =
        Math.min(
          8,
          renderer.capabilities.getMaxAnisotropy()
        );

      texture.needsUpdate =
        true;

      return texture;

    };


    /* =======================================================
       可点击馆藏

       按安全预览提供的馆藏封面陈列书册；
       场景不读取报告正文或数值。
       同一边馆藏较多时自动横向排开并缩小，避免重叠。
    ======================================================= */

    const picks:
      THREE.Object3D[] = [];

    type ReportBook = {
      root: THREE.Group;
      glowMaterials: THREE.MeshStandardMaterial[];
      baseX: number;
      baseY: number;
      baseZ: number;
      baseRotationY: number;
      baseScale: number;
      takeOffsetX: number;
      takeOffsetZ: number;
      takeFaceRotationY: number;
    };

    const reportBooks:
      Array<ReportBook | undefined> = [];


    /* =======================================================
       外景
       保留原项目 architecture.ts
    ======================================================= */

    if (
      mode === "exterior"
    ) {

      buildLibraryArchitecture(
        group
      );

    }


    /* =======================================================
       室内
       室内中庭
    ======================================================= */

    else {

      const loader =
        new GLTFLoader();


      loader.load(

        `${import.meta.env.BASE_URL}models/yunnan_library_atrium.glb`,


        /* ---------------------------------------------------
           加载成功
        --------------------------------------------------- */

        (gltf) => {

          if (disposed) {

            gltf.scene.traverse(
              object => {

                if (
                  object instanceof
                  THREE.Mesh
                ) {

                  object.geometry.dispose();

                }

              }
            );

            return;

          }


          const model =
            gltf.scene;


          model.name =
            "YNU_ATRIUM";


          model.position.set(
            0,
            0,
            0
          );


          /* -----------------------------------------------
             处理中庭建筑外观
          ----------------------------------------------- */

          model.traverse(

            object => {

              if (
                object instanceof
                THREE.Mesh
              ) {

                object.castShadow =
                  true;


                object.receiveShadow =
                  true;


                const materials =

                  Array.isArray(
                    object.material
                  )

                    ? object.material

                    : [
                        object.material
                      ];


                materials.forEach(

                  material => {

                    const materialName =
                      material.name
                        .toLowerCase();

                    const objectName =
                      object.name
                        .toLowerCase();

                    const standard =
                      material as THREE.MeshStandardMaterial;

                    /* ---------------------------------------
                       玻璃：保留透光，不写入深度，避免窗面发黑
                    --------------------------------------- */

                    if (
                      material.transparent ||
                      materialName.includes("glass") ||
                      objectName.includes("glass") ||
                      objectName.includes("dome")
                    ) {

                      material.transparent =
                        true;

                      material.depthWrite =
                        false;

                      if (
                        "opacity" in material
                      ) {
                        (material as THREE.MeshStandardMaterial).opacity =
                          Math.min(
                            0.72,
                            (material as THREE.MeshStandardMaterial).opacity || 0.72
                          );
                      }

                    }

                    /* ---------------------------------------
                       PBR 环境反射强度
                    --------------------------------------- */

                    if (
                      standard.isMeshStandardMaterial
                    ) {

                      standard.envMapIntensity =
                        0.20;

                      /* 红木栏杆：较亮但不要塑料高光 */
                      if (
                        materialName.includes("railwood") ||
                        objectName.includes("railings")
                      ) {
                        standard.color.setHex(
                          0x5a2417
                        );
                        standard.roughness =
                          0.46;
                        standard.metalness =
                          0.015;
                        standard.envMapIntensity =
                          0.34;
                      }

                      /* 中央台 / 自习桌：比栏杆更沉稳 */
                      else if (
                        materialName.includes("wooddark")
                      ) {
                        standard.color.setHex(
                          0x2a1812
                        );
                        standard.roughness =
                          0.30;
                        standard.envMapIntensity =
                          0.30;
                      }

                      else if (
                        materialName.includes("woodlight")
                      ) {
                        standard.color.setHex(
                          0x6a3522
                        );
                        standard.roughness =
                          0.43;
                        standard.envMapIntensity =
                          0.32;
                      }

                      else if (
                        materialName.includes("ynu_wood") ||
                        materialName === "wood"
                      ) {
                        standard.color.setHex(
                          0x51261a
                        );
                        standard.roughness =
                          0.45;
                        standard.envMapIntensity =
                          0.30;
                      }

                      /* 石材 / 柱体：暖白、柔和反射 */
                      if (
                        materialName.includes("stone") ||
                        objectName.includes("column") ||
                        objectName.includes("floorring")
                      ) {
                        if (
                          materialName.includes("stonedark")
                        ) {
                          standard.color.setHex(
                            0x403930
                          );
                          standard.roughness =
                            0.76;
                        }
                        else if (
                          objectName.includes("column")
                        ) {
                          standard.color.setHex(
                            0xaaa18e
                          );
                          standard.roughness =
                            0.74;
                        }
                        else {
                          standard.color.setHex(
                            0xb7ae9b
                          );
                          standard.roughness =
                            0.72;
                        }
                        standard.envMapIntensity =
                          0.28;
                      }

                      /* 暖米色墙面压亮度，避免整座大厅发白 */
                      if (
                        materialName.includes("warmwall") ||
                        objectName.includes("background_walls")
                      ) {
                        standard.color.setHex(
                          0x5f594f
                        );
                        standard.roughness =
                          0.80;
                        standard.envMapIntensity =
                          0.12;
                      }

                      /* 绿植：单独提亮。
                         V6 模型的叶片基础色本来就很深，
                         再做 HSL 压暗会在 ACES 下接近黑色。 */
                      if (
                        materialName.includes("leaf") ||
                        objectName.includes("plantleaf") ||
                        objectName.includes("plant_leaf")
                      ) {
                        const leafIsLight =
                          materialName.includes("light") ||
                          objectName.includes("light");

                        standard.color.setHex(
                          leafIsLight
                            ? 0x4f9657
                            : 0x347743
                        );
                        standard.roughness = 0.86;
                        standard.metalness = 0.0;
                        standard.envMapIntensity = 0.12;
                        standard.emissive.setHex(0x0b2312);
                        standard.emissiveIntensity = 0.16;
                      }

                      /* 花朵不要被阴影压成黑红色 */
                      if (
                        materialName.includes("flower") ||
                        objectName.includes("plantflower") ||
                        objectName.includes("plant_flower")
                      ) {
                        standard.color.setHex(0xa94a4d);
                        standard.roughness = 0.78;
                        standard.metalness = 0.0;
                        standard.envMapIntensity = 0.10;
                        standard.emissive.setHex(0x240809);
                        standard.emissiveIntensity = 0.10;
                      }

                      /* 花盆压成暖灰白，避免和楼板一起炸白 */
                      if (
                        materialName.includes("plantpot") ||
                        objectName.includes("plantpot") ||
                        objectName.includes("plant_pot")
                      ) {
                        standard.color.setHex(0xbdb5a5);
                        standard.roughness = 0.88;
                        standard.metalness = 0.0;
                        standard.envMapIntensity = 0.10;
                      }

                      /* 窗面/天光面板：避免纯白发光 */
                      if (
                        materialName.includes("glass") ||
                        materialName.includes("sky") ||
                        objectName.includes("window")
                      ) {
                        standard.color.setHex(0x91a9ad);
                        standard.roughness = Math.max(standard.roughness, 0.26);
                        standard.metalness = 0.0;
                        standard.envMapIntensity = 0.08;
                      }

                      /* 灯带：保留暖色，不让曝光把它炸白 */
                      if (
                        materialName.includes("lightstrip")
                      ) {
                        standard.toneMapped =
                          true;
                        standard.envMapIntensity =
                          0.10;
                        if (
                          "emissiveIntensity" in standard
                        ) {
                          standard.emissiveIntensity =
                            Math.min(
                              standard.emissiveIntensity || 0.45,
                              0.45
                            );
                        }
                      }

                    }

                    material.needsUpdate =
                      true;

                  }

                );

              }

            }

          );


          group.add(
            model
          );


          /* =================================================
             读取 Blender 热点
          ================================================= */

          const bookHotspot =
            model.getObjectByName(
              "HOTSPOT_BOOK"
            );


          const collectionHotspot =
            model.getObjectByName(
              "HOTSPOT_COLLECTION"
            );


          const dataHotspot =
            model.getObjectByName(
              "HOTSPOT_DATA"
            );


          console.log(
            "云南大学中庭模型加载完成",
            {
              bookHotspot,
              collectionHotspot,
              dataHotspot,
            }
          );


          /* =================================================
             中央八边形馆藏陈列（V6 锚点驱动）

             Blender V6 已提供 BOOK_SLOT_00 ~ BOOK_SLOT_07。
             当前 4 期会自动占用 0 / 2 / 4 / 6 四个边；
             后续增加历年报告时无需再改这里：
             - <= 8 册：均匀分配到 8 个边
             - > 8 册：每个边自动容纳多册并横向排开
          ================================================= */

          const catalog =
            books
              .map((book, index) => {
                const issueNumber = book.cover[2].match(/总第\s*(\d+)\s*期/)?.[1] ?? "—";
                const month = book.cover[3].match(/\d{4}年\d{1,2}月/)?.[0] ?? book.cover[2];
                return { index, period: month, no: issueNumber };
              })
              .sort((a, b) =>
                a.period.localeCompare(b.period)
              );

          /*
            优先读取 Blender V6 里的 8 个锚点。
            如果某个 GLB 没有这些 Empty，才退回数学计算位置。
          */
          group.updateWorldMatrix(
            true,
            true
          );

          model.updateWorldMatrix(
            true,
            true
          );

          const fallbackRadius = 3.20;
          const fallbackSurfaceY = 0.84;

          const slotPositions =
            Array.from(
              { length: 8 },
              (_, slotIndex) => {
                const anchor =
                  model.getObjectByName(
                    `BOOK_SLOT_${String(slotIndex).padStart(2, "0")}`
                  );

                if (anchor) {
                  const world =
                    new THREE.Vector3();

                  anchor.getWorldPosition(
                    world
                  );

                  /*
                    BOOK_SLOT 位于桌面，而 Three.js 书 root 位于书本中心。
                    所以后面会在 Y 上再加半本书高度。
                  */
                  return group.worldToLocal(
                    world.clone()
                  );
                }

                const edgeAngle =
                  slotIndex *
                  Math.PI / 4;

                return new THREE.Vector3(
                  Math.sin(edgeAngle) * fallbackRadius,
                  fallbackSurfaceY,
                  Math.cos(edgeAngle) * fallbackRadius
                );
              }
            );

          const edgeGroups =
            Array.from(
              { length: 8 },
              () => [] as typeof catalog
            );

          if (
            catalog.length <= 8
          ) {
            /*
              少于 8 册时均匀铺开。
              4 册 => 0 / 2 / 4 / 6，正好隔边陈列。
            */
            catalog.forEach(
              (item, order) => {
                const slotIndex =
                  Math.floor(
                    order * 8 /
                    Math.max(1, catalog.length)
                  ) % 8;

                edgeGroups[
                  slotIndex
                ].push(item);
              }
            );
          }
          else {
            catalog.forEach(
              (item, order) => {
                edgeGroups[
                  order % 8
                ].push(item);
              }
            );
          }

          const maxOnOneEdge =
            Math.max(
              1,
              ...edgeGroups.map(
                items => items.length
              )
            );

          const baseScale =
            Math.max(
              0.54,
              1 -
                Math.max(
                  0,
                  maxOnOneEdge - 1
                ) * 0.11
            );

          const tangentSpacing =
            maxOnOneEdge <= 1
              ? 0
              : Math.min(
                  0.74,
                  2.25 /
                    (maxOnOneEdge - 1)
                );

          const bookHeight = 1.08;

          edgeGroups.forEach(
            (items, edgeIndex) => {

              if (!items.length) return;

              const slot =
                slotPositions[
                  edgeIndex
                ];

              const radial =
                new THREE.Vector2(
                  slot.x,
                  slot.z
                );

              if (
                radial.lengthSq() <
                0.0001
              ) {
                radial.set(
                  Math.sin(
                    edgeIndex *
                    Math.PI / 4
                  ),
                  Math.cos(
                    edgeIndex *
                    Math.PI / 4
                  )
                );
              }

              radial.normalize();

              const radialX =
                radial.x;

              const radialZ =
                radial.y;

              const tangentX =
                radialZ;

              const tangentZ =
                -radialX;

              const edgeAngle =
                Math.atan2(
                  radialX,
                  radialZ
                );

              /*
                锚点 Y 就是 Blender 下层八角桌的真实桌面高度。
                书 root 在中心，所以加半本书高度。
              */
              const bookBaseY =
                slot.y +
                bookHeight *
                baseScale / 2;

              items.forEach(
                (item, itemOnEdge) => {

                  const tangentOffset =
                    (
                      itemOnEdge -
                      (items.length - 1) / 2
                    ) *
                    tangentSpacing;

                  const baseX =
                    slot.x +
                    tangentX *
                      tangentOffset;

                  const baseZ =
                    slot.z +
                    tangentZ *
                      tangentOffset;

                  const root =
                    new THREE.Group();

                  root.position.set(
                    baseX,
                    bookBaseY,
                    baseZ
                  );

                  /*
                    封面朝八边形外侧。点击后再旋转正对当前相机。
                  */
                  root.rotation.y =
                    edgeAngle;

                  root.scale.setScalar(
                    baseScale
                  );

                  root.userData.issue =
                    item.index;

                  root.userData.type =
                    "report-root";

                  group.add(root);


                  const bookMaterial =
                    new THREE.MeshStandardMaterial({
                      color: 0x123b2a,
                      roughness: 0.56,
                      metalness: 0.03,
                      emissive: 0x000000,
                      emissiveIntensity: 0,
                    });

                  const body =
                    new THREE.Mesh(
                      new THREE.BoxGeometry(
                        0.78,
                        1.08,
                        0.22
                      ),
                      bookMaterial
                    );

                  body.castShadow = true;
                  body.receiveShadow = true;
                  body.userData.issue =
                    item.index;
                  body.userData.type =
                    "report";
                  root.add(body);


                  const spineMaterial =
                    new THREE.MeshStandardMaterial({
                      color: 0x0d2f22,
                      roughness: 0.52,
                      metalness: 0.02,
                      emissive: 0x000000,
                      emissiveIntensity: 0,
                    });

                  const spine =
                    new THREE.Mesh(
                      new THREE.BoxGeometry(
                        0.055,
                        0.96,
                        0.23
                      ),
                      spineMaterial
                    );

                  spine.position.x = -0.34;
                  spine.castShadow = true;
                  spine.receiveShadow = true;
                  root.add(spine);


                  /* 图3风格的封面金色竖向收边 */
                  const trimMaterial =
                    new THREE.MeshStandardMaterial({
                      color: 0xd1bd82,
                      roughness: 0.34,
                      metalness: 0.16,
                    });

                  [
                    -0.365,
                    0.365,
                  ].forEach(
                    x => {
                      const trim =
                        new THREE.Mesh(
                          new THREE.BoxGeometry(
                            0.018,
                            1.02,
                            0.235
                          ),
                          trimMaterial
                        );
                      trim.position.x = x;
                      trim.castShadow = true;
                      root.add(trim);
                    }
                  );


                  const coverTexture =
                    textTex(
                      [
                        "学科信息参考",
                        `总第 ${item.no} 期`,
                        item.period,
                      ],
                      "#193f33",
                      "#e4d9b9",
                      512,
                      640
                    );

                  const coverMaterial =
                    new THREE.MeshStandardMaterial({
                      map: coverTexture,
                      roughness: 0.52,
                      metalness: 0.02,
                      emissive: 0x000000,
                      emissiveIntensity: 0,
                    });

                  const cover =
                    new THREE.Mesh(
                      new THREE.PlaneGeometry(
                        0.68,
                        0.97
                      ),
                      coverMaterial
                    );

                  cover.position.z = 0.118;
                  cover.userData.issue =
                    item.index;
                  cover.userData.type =
                    "report";
                  root.add(cover);


                  /*
                    点击命中盒跟随书本一起缩放/旋转。
                  */
                  const hitMaterial =
                    new THREE.MeshBasicMaterial({
                      transparent: true,
                      opacity: 0,
                      depthWrite: false,
                    });

                  const hitBox =
                    new THREE.Mesh(
                      new THREE.BoxGeometry(
                        1.02,
                        1.44,
                        0.86
                      ),
                      hitMaterial
                    );

                  hitBox.position.z = 0.18;
                  hitBox.userData.issue =
                    item.index;
                  hitBox.userData.type =
                    "report-hitbox";
                  root.add(hitBox);
                  picks.push(hitBox);

                  reportBooks[
                    item.index
                  ] = {
                    root,
                    glowMaterials: [
                      bookMaterial,
                      spineMaterial,
                      coverMaterial,
                    ],
                    baseX,
                    baseY: bookBaseY,
                    baseZ,
                    baseRotationY:
                      edgeAngle,
                    baseScale,
                    takeOffsetX: 0,
                    takeOffsetZ: 0,
                    takeFaceRotationY:
                      edgeAngle,
                  };
                }
              );
            }
          );
        },


        /* ---------------------------------------------------
           Loading Progress
        --------------------------------------------------- */

        xhr => {

          if (
            xhr.total
          ) {

            const percent =

              (
                xhr.loaded /
                xhr.total *
                100
              ).toFixed(0);


            console.log(

              `云南大学中庭加载：${percent}%`

            );

          }

        },


        /* ---------------------------------------------------
           加载失败
        --------------------------------------------------- */

        error => {

          console.error(

            "云南大学图书馆中庭 GLB 加载失败：",

            error

          );


          setFallback(
            true
          );


          renderer.domElement.style.display =
            "none";

        }

      );

    }


    /* =======================================================
       Camera Orbit 参数
    ======================================================= */

    const orbit =
      origin
        .clone()
        .sub(
          target
        );


    let azimuth =
      Math.atan2(

        orbit.x,

        orbit.z

      );


    let elevation =
      Math.asin(

        orbit.y /
        orbit.length()

      );


    let distance =
      orbit.length();


    /* =======================================================
       鼠标状态
    ======================================================= */

    let width =
      0;


    let height =
      0;


    let frame =
      0;


    let mouse =
      0;


    let hover =
      -1;


    let dragging =
      false;


    let dragged =
      false;


    let lastX =
      0;


    let lastY =
      0;


    /* =======================================================
       取书镜头动画状态

       点击馆藏后不立即切 reader：
       先让镜头推进到被选中的书，再进入阅读界面。
    ======================================================= */

    let takingIssue =
      -1;

    let takeStart =
      0;

    let takeDuration =
      900;

    let takeDispatched =
      false;

    const takeStartCamera =
      new THREE.Vector3();

    const takeEndCamera =
      new THREE.Vector3();

    const takeStartLook =
      new THREE.Vector3();

    const takeEndLook =
      new THREE.Vector3();

    let takeStartFov =
      ROOM_CAMERA_FOV;


    /* =======================================================
       归架镜头动画状态

       从阅读器返回大厅时，先从所选书册的近景开始，
       再把书放回展台并退回一楼默认视角。
    ======================================================= */

    let returnInitialized =
      false;

    let returnFinished =
      false;

    let returnStart =
      0;

    const returnDuration =
      820;

    const returnStartCamera =
      new THREE.Vector3();

    const returnEndCamera =
      ROOM_CAMERA_POSITION.clone();

    const returnStartLook =
      new THREE.Vector3();

    const returnEndLook =
      ROOM_CAMERA_TARGET.clone();


    /* =======================================================
       Resize
    ======================================================= */

    const resize = () => {

      width =
        mount.clientWidth;


      height =
        mount.clientHeight;


      camera.aspect =
        width /
        height;


      /*
        不同设备的 FOV
      */

      if (
        width < 700
      ) {

        camera.fov =

          mode === "exterior"

            ? 56

            : 58;

      }

      else {

        camera.fov =

          mode === "exterior"

            ? 36

            : ROOM_CAMERA_FOV;

      }


      if (
        mode === "exterior" &&
        width < 700
      ) {

        distance =
          Math.max(
            distance,
            70
          );

      }


      camera.updateProjectionMatrix();


      renderer.setSize(
        width,
        height
      );

    };


    resize();


    const resizeObserver =
      new ResizeObserver(
        resize
      );


    resizeObserver.observe(
      mount
    );


    /* =======================================================
       Raycaster
    ======================================================= */

    const ray =
      new THREE.Raycaster();


    const pointer =
      new THREE.Vector2();


    const issueAtPointer = (
      clientX: number,
      clientY: number
    ) => {

      const rect =
        renderer.domElement
          .getBoundingClientRect();

      pointer.set(
        (
          (clientX - rect.left) /
          rect.width
        ) * 2 - 1,
        -(
          (clientY - rect.top) /
          rect.height
        ) * 2 + 1
      );

      ray.setFromCamera(
        pointer,
        camera
      );

      const hit =
        ray.intersectObjects(
          picks,
          false
        )[0];

      return hit
        ? Number(
            hit.object.userData.issue
          )
        : -1;
    };


    /* =======================================================
       Pointer Move
    ======================================================= */

    const move = (
      event: PointerEvent
    ) => {

      const rect =
        renderer.domElement
          .getBoundingClientRect();

      if (
        takingIssue >= 0
      ) {
        renderer.domElement.style.cursor =
          "progress";
        return;
      }


      mouse =

        (
          (
            event.clientX -
            rect.left
          ) /
          rect.width -
          0.5
        ) * 2;


      /* ---------------------------------------------------
         拖动旋转
      --------------------------------------------------- */

      if (
        dragging
      ) {

        const dx =
          event.clientX -
          lastX;


        const dy =
          event.clientY -
          lastY;


        if (
          Math.abs(dx) > 1 ||
          Math.abs(dy) > 1
        ) {

          dragged =
            true;

        }


        azimuth -=
          dx *
          0.005;


        elevation +=
          dy *
          0.004;


        /* -------------------------------
           外景角度限制
        ------------------------------- */

        if (
          mode === "exterior"
        ) {

          elevation =
            Math.max(

              0.07,

              Math.min(
                1.25,
                elevation
              )

            );

        }


        /* -------------------------------
           室内角度限制
        ------------------------------- */

        else {

          elevation =
            Math.max(

              -0.45,

              Math.min(
                0.70,
                elevation
              )

            );

        }


        lastX =
          event.clientX;


        lastY =
          event.clientY;

      }


      /* ---------------------------------------------------
         室内图书 Hover
      --------------------------------------------------- */

      if (
        mode === "room"
      ) {

        hover =
          issueAtPointer(
            event.clientX,
            event.clientY
          );


        if (
          dragging
        ) {

          renderer.domElement.style.cursor =
            "grabbing";

        }

        else {

          renderer.domElement.style.cursor =

            hover >= 0

              ? "pointer"

              : "grab";

        }

      }

    };


    /* =======================================================
       Pointer Down
    ======================================================= */

    const down = (
      event: PointerEvent
    ) => {

      if (
        enteringRef.current ||
        takingIssue >= 0
      ) {

        return;

      }


      dragging =
        true;


      dragged =
        false;


      lastX =
        event.clientX;


      lastY =
        event.clientY;


      renderer.domElement.style.cursor =
        "grabbing";


      renderer.domElement.setPointerCapture(
        event.pointerId
      );

    };


    /* =======================================================
       Pointer Up
    ======================================================= */

    const up = (
      event: PointerEvent
    ) => {

      dragging =
        false;


      try {

        renderer.domElement.releasePointerCapture(
          event.pointerId
        );

      }

      catch {
        //
      }


      renderer.domElement.style.cursor =

        mode === "room"

          ? (
              hover >= 0

                ? "pointer"

                : "grab"
            )

          : "grab";

    };


    /* =======================================================
       Zoom
    ======================================================= */

    const wheel = (
      event: WheelEvent
    ) => {

      if (
        enteringRef.current ||
        takingIssue >= 0
      ) {

        return;

      }


      event.preventDefault();


      if (
        mode === "exterior"
      ) {

        distance =
          Math.max(

            26,

            Math.min(

              90,

              distance +
              event.deltaY *
              0.025

            )

          );

      }

      else {

        distance =
          Math.max(

            5.5,

            Math.min(

              20,

              distance +
              event.deltaY *
              0.008

            )

          );

      }

    };


    /* =======================================================
       Click Book
    ======================================================= */

    const click = (
      event: MouseEvent
    ) => {

      if (
        mode !== "room" ||
        dragged ||
        takingIssue >= 0 ||
        returnIssue !== null
      ) {
        return;
      }

      const clickedIssue =
        issueAtPointer(
          event.clientX,
          event.clientY
        );

      if (
        clickedIssue < 0
      ) {
        return;
      }

      takeStartRef.current?.(
        clickedIssue
      );

      /*
        用户关闭动效 / 系统偏好减少动态时，
        直接进入阅读器，不强行动画。
      */
      if (
        !motionRef.current
      ) {
        pick.current(
          clickedIssue
        );
        return;
      }

      const selectedBook =
        reportBooks[
          clickedIssue
        ];

      if (
        !selectedBook
      ) {
        pick.current(
          clickedIssue
        );
        return;
      }

      takingIssue =
        clickedIssue;

      hover =
        clickedIssue;

      takeStart =
        performance.now();

      takeDuration =
        900;

      takeDispatched =
        false;

      takeStartCamera.copy(
        camera.position
      );

      takeStartFov =
        camera.fov;

      /*
        从当前真正的镜头朝向取得起始观察点，
        因此即使用户已经拖动过室内视角，
        动画也不会突然跳回默认方向。
      */
      const startDirection =
        new THREE.Vector3();

      camera.getWorldDirection(
        startDirection
      );

      takeStartLook.copy(
        camera.position
      ).add(
        startDirection.multiplyScalar(
          10
        )
      );

      selectedBook.root.updateWorldMatrix(
        true,
        false
      );

      const bookWorld =
        new THREE.Vector3();

      selectedBook.root.getWorldPosition(
        bookWorld
      );

      /*
        取书时先让封面旋转朝向当前相机，
        再沿“书 -> 相机”的水平向量轻微抽离八角桌。
      */
      const bookToCamera =
        camera.position
          .clone()
          .sub(bookWorld);

      bookToCamera.y = 0;

      if (
        bookToCamera.lengthSq() <
        0.0001
      ) {
        bookToCamera.set(
          0,
          0,
          1
        );
      }

      bookToCamera.normalize();

      selectedBook.takeOffsetX =
        bookToCamera.x * 0.58;

      selectedBook.takeOffsetZ =
        bookToCamera.z * 0.58;

      selectedBook.takeFaceRotationY =
        Math.atan2(
          bookToCamera.x,
          bookToCamera.z
        );

      takeEndLook.copy(
        bookWorld
      );

      takeEndLook.y +=
        0.18;

      const approachDirection =
        takeStartCamera
          .clone()
          .sub(
            bookWorld
          )
          .normalize();

      takeEndCamera.copy(
        bookWorld
      ).add(
        approachDirection.multiplyScalar(
          3.15
        )
      );

      /*
        稍微抬高最终镜头，避免推进后只看到书的下半部。
      */
      takeEndCamera.y +=
        0.48;

      renderer.domElement.style.cursor =
        "progress";

    };


    /* =======================================================
       Listeners
    ======================================================= */

    renderer.domElement.addEventListener(
      "pointermove",
      move
    );


    renderer.domElement.addEventListener(
      "pointerdown",
      down
    );


    renderer.domElement.addEventListener(
      "pointerup",
      up
    );


    renderer.domElement.addEventListener(
      "pointercancel",
      up
    );


    renderer.domElement.addEventListener(
      "wheel",
      wheel,
      {
        passive: false,
      }
    );


    renderer.domElement.addEventListener(
      "click",
      click
    );


    renderer.domElement.style.cursor =
      "grab";


    /* =======================================================
       Render Loop
    ======================================================= */

    const tick = () => {

      /* ---------------------------------------------------
         外景
      --------------------------------------------------- */

      if (
        mode === "exterior"
      ) {

        const approach =

          enteringRef.current

            ? Math.min(

                1,

                (
                  performance.now() -
                  entryStart.current
                ) /
                1050

              )

            : 0;


        const smooth =

          approach *
          approach *
          (
            3 -
            2 * approach
          );


        const horizontal =

          Math.cos(
            elevation
          ) *
          distance;


        const orbitPosition =
          new THREE.Vector3(

            target.x +
              Math.sin(
                azimuth
              ) *
                horizontal,

            target.y +
              Math.sin(
                elevation
              ) *
                distance,

            target.z +
              Math.cos(
                azimuth
              ) *
                horizontal

          );


        /*
          点击进入后
          镜头向建筑入口推进
        */

        camera.position.copy(

          orbitPosition.lerp(

            new THREE.Vector3(
              0,
              3.8,
              11
            ),

            smooth

          )

        );


        camera.lookAt(

          0,

          5.8 -
            smooth *
            2.2,

          2

        );

      }


      /* ---------------------------------------------------
         室内中庭
      --------------------------------------------------- */

      else {

        if (
          returnIssue !== null
        ) {

          const returningBook =
            reportBooks[returnIssue];

          if (
            returningBook &&
            !returnInitialized
          ) {
            returningBook.root.updateWorldMatrix(
              true,
              false
            );

            const bookWorld =
              new THREE.Vector3();

            returningBook.root.getWorldPosition(
              bookWorld
            );

            const approachDirection =
              ROOM_CAMERA_POSITION
                .clone()
                .sub(bookWorld)
                .normalize();

            returnStartCamera.copy(
              bookWorld
            ).add(
              approachDirection.multiplyScalar(
                3.15
              )
            );

            returnStartCamera.y +=
              0.48;

            returnStartLook.copy(
              bookWorld
            );

            returnStartLook.y +=
              0.18;

            const returnBookToCamera =
              ROOM_CAMERA_POSITION
                .clone()
                .sub(bookWorld);

            returnBookToCamera.y = 0;

            if (
              returnBookToCamera.lengthSq() <
              0.0001
            ) {
              returnBookToCamera.set(
                0,
                0,
                1
              );
            }

            returnBookToCamera.normalize();

            returningBook.takeOffsetX =
              returnBookToCamera.x * 0.58;

            returningBook.takeOffsetZ =
              returnBookToCamera.z * 0.58;

            returningBook.takeFaceRotationY =
              Math.atan2(
                returnBookToCamera.x,
                returnBookToCamera.z
              );

            returningBook.root.position.x =
              returningBook.baseX +
              returningBook.takeOffsetX;

            returningBook.root.position.y =
              returningBook.baseY +
              0.34;

            returningBook.root.position.z =
              returningBook.baseZ +
              returningBook.takeOffsetZ;

            returningBook.root.rotation.y =
              returningBook.takeFaceRotationY;

            returningBook.root.scale.setScalar(
              returningBook.baseScale *
              1.16
            );

            returningBook.glowMaterials.forEach(
              material => {
                material.emissive.setHex(
                  0x8b6f35
                );
                material.emissiveIntensity =
                  0.78;
              }
            );

            camera.position.copy(
              returnStartCamera
            );

            camera.lookAt(
              returnStartLook
            );

            camera.fov =
              37;

            camera.updateProjectionMatrix();

            returnStart =
              performance.now();

            returnInitialized =
              true;

            renderer.domElement.style.opacity =
              "1";
          }

          if (
            returnInitialized
          ) {
            const elapsed =
              performance.now() -
              returnStart;

            const progress =
              Math.min(
                1,
                elapsed /
                  returnDuration
              );

            const smooth =
              progress < 0.5
                ? 4 * progress * progress * progress
                : 1 -
                  Math.pow(
                    -2 * progress + 2,
                    3
                  ) / 2;

            camera.position.lerpVectors(
              returnStartCamera,
              returnEndCamera,
              smooth
            );

            const returnLook =
              returnStartLook
                .clone()
                .lerp(
                  returnEndLook,
                  smooth
                );

            camera.lookAt(
              returnLook
            );

            camera.fov =
              THREE.MathUtils.lerp(
                37,
                ROOM_CAMERA_FOV,
                smooth
              );

            camera.updateProjectionMatrix();

            const returningBook =
              reportBooks[returnIssue];

            if (
              returningBook
            ) {
              returningBook.root.position.x =
                THREE.MathUtils.lerp(
                  returningBook.baseX +
                    returningBook.takeOffsetX,
                  returningBook.baseX,
                  smooth
                );

              returningBook.root.position.y =
                THREE.MathUtils.lerp(
                  returningBook.baseY + 0.34,
                  returningBook.baseY,
                  smooth
                );

              returningBook.root.position.z =
                THREE.MathUtils.lerp(
                  returningBook.baseZ +
                    returningBook.takeOffsetZ,
                  returningBook.baseZ,
                  smooth
                );

              const returnRotationDelta =
                Math.atan2(
                  Math.sin(
                    returningBook.baseRotationY -
                    returningBook.takeFaceRotationY
                  ),
                  Math.cos(
                    returningBook.baseRotationY -
                    returningBook.takeFaceRotationY
                  )
                );

              returningBook.root.rotation.y =
                returningBook.takeFaceRotationY +
                returnRotationDelta * smooth;

              returningBook.root.scale.setScalar(
                THREE.MathUtils.lerp(
                  returningBook.baseScale * 1.16,
                  returningBook.baseScale,
                  smooth
                )
              );

              returningBook.glowMaterials.forEach(
                material => {
                  material.emissive.setHex(
                    smooth < 0.96
                      ? 0x8b6f35
                      : 0x000000
                  );
                  material.emissiveIntensity =
                    THREE.MathUtils.lerp(
                      0.78,
                      0,
                      smooth
                    );
                }
              );
            }

            if (
              progress >= 1 &&
              !returnFinished
            ) {
              returnFinished =
                true;

              returnCompleteRef.current?.();
            }
          }

        }

        else if (
          takingIssue >= 0
        ) {

          const elapsed =
            performance.now() -
            takeStart;

          const progress =
            Math.min(
              1,
              elapsed /
                takeDuration
            );

          /*
            取书分两拍：
            先让书原地旋转面向读者，再让镜头推进。
          */
          const cameraProgress =
            THREE.MathUtils.clamp(
              (progress - 0.24) /
              0.76,
              0,
              1
            );

          const smooth =
            cameraProgress < 0.5
              ? 4 * cameraProgress * cameraProgress * cameraProgress
              : 1 -
                Math.pow(
                  -2 * cameraProgress + 2,
                  3
                ) / 2;

          camera.position.lerpVectors(
            takeStartCamera,
            takeEndCamera,
            smooth
          );

          const takeLook =
            takeStartLook
              .clone()
              .lerp(
                takeEndLook,
                smooth
              );

          camera.lookAt(
            takeLook
          );

          camera.fov =
            THREE.MathUtils.lerp(
              takeStartFov,
              37,
              smooth
            );

          camera.updateProjectionMatrix();

          if (
            progress >= 1 &&
            !takeDispatched
          ) {
            takeDispatched =
              true;

            pick.current(
              takingIssue
            );
          }

        }

        else {

          const horizontal =

            Math.cos(
              elevation
            ) *
            distance;


          camera.position.set(

            target.x +
              Math.sin(
                azimuth
              ) *
                horizontal,

            target.y +
              Math.sin(
                elevation
              ) *
                distance,

            target.z +
              Math.cos(
                azimuth
              ) *
                horizontal

          );


          /*
            打开动态效果时
            鼠标有非常轻微的视差
          */

          const lookTarget =
            target.clone();


          if (
            motionRef.current &&
            !dragging
          ) {

            lookTarget.x +=
              mouse *
              0.16;

          }


          camera.lookAt(
            lookTarget
          );

        }


        reportBooks.forEach(
          (book, index) => {

            if (
              returnIssue !== null &&
              returnInitialized &&
              index === returnIssue
            ) {
              return;
            }

            const active =
              hover === index;

            const taking =
              takingIssue === index;

            if (!book) {
              return;
            }

            const liveTakeProgress =
              taking
                ? THREE.MathUtils.clamp(
                    (
                      performance.now() -
                      takeStart
                    ) /
                    takeDuration,
                    0,
                    1
                  )
                : 0;

            const rotatePhase =
              taking
                ? THREE.MathUtils.smoothstep(
                    liveTakeProgress,
                    0,
                    0.36
                  )
                : 0;

            const liftPhase =
              taking
                ? THREE.MathUtils.smoothstep(
                    liveTakeProgress,
                    0.12,
                    0.58
                  )
                : 0;

            const pullPhase =
              taking
                ? THREE.MathUtils.smoothstep(
                    liveTakeProgress,
                    0.30,
                    0.84
                  )
                : 0;

            book.root.position.x =
              THREE.MathUtils.lerp(
                book.root.position.x,
                book.baseX +
                  book.takeOffsetX *
                  pullPhase,
                taking
                  ? 0.28
                  : 0.16
              );

            book.root.position.y =
              THREE.MathUtils.lerp(
                book.root.position.y,
                book.baseY +
                  (
                    taking
                      ? 0.34 * liftPhase
                      : active
                        ? 0.18
                        : 0
                  ),
                taking
                  ? 0.28
                  : 0.16
              );

            book.root.position.z =
              THREE.MathUtils.lerp(
                book.root.position.z,
                book.baseZ +
                  book.takeOffsetZ *
                  pullPhase,
                taking
                  ? 0.28
                  : 0.16
              );

            const faceDelta =
              Math.atan2(
                Math.sin(
                  book.takeFaceRotationY -
                  book.baseRotationY
                ),
                Math.cos(
                  book.takeFaceRotationY -
                  book.baseRotationY
                )
              );

            const rotationTarget =
              taking
                ? book.baseRotationY +
                  faceDelta *
                  rotatePhase
                : book.baseRotationY;

            const rotationDelta =
              Math.atan2(
                Math.sin(
                  rotationTarget -
                  book.root.rotation.y
                ),
                Math.cos(
                  rotationTarget -
                  book.root.rotation.y
                )
              );

            book.root.rotation.y +=
              rotationDelta *
              (taking ? 0.34 : 0.16);

            const targetScale =
              book.baseScale *
              (
                taking
                  ? 1 + 0.16 * pullPhase
                  : active
                    ? 1.08
                    : 1
              );

            const nextScale =
              THREE.MathUtils.lerp(
                book.root.scale.x,
                targetScale,
                taking
                  ? 0.20
                  : 0.16
              );

            book.root.scale.setScalar(
              nextScale
            );

            book.glowMaterials.forEach(
              material => {
                material.emissive.setHex(
                  taking
                    ? 0x8b6f35
                    : active
                      ? 0x6b5b2f
                      : 0x000000
                );
                material.emissiveIntensity =
                  THREE.MathUtils.lerp(
                    material.emissiveIntensity,
                    taking
                      ? 0.78
                      : active
                        ? 0.52
                        : 0,
                    taking
                      ? 0.22
                      : 0.18
                  );
              }
            );
          }
        );

      }


      renderer.render(

        scene,

        camera

      );


      frame =
        requestAnimationFrame(
          tick
        );

    };


    tick();


    /* =======================================================
       清理资源
    ======================================================= */

    return () => {

      disposed =
        true;


      cancelAnimationFrame(
        frame
      );


      resizeObserver.disconnect();


      renderer.domElement.removeEventListener(
        "pointermove",
        move
      );


      renderer.domElement.removeEventListener(
        "pointerdown",
        down
      );


      renderer.domElement.removeEventListener(
        "pointerup",
        up
      );


      renderer.domElement.removeEventListener(
        "pointercancel",
        up
      );


      renderer.domElement.removeEventListener(
        "wheel",
        wheel
      );


      renderer.domElement.removeEventListener(
        "click",
        click
      );


      scene.traverse(
        object => {

          if (
            object instanceof
            THREE.Mesh
          ) {

            object.geometry.dispose();


            const materials =

              Array.isArray(
                object.material
              )

                ? object.material

                : [
                    object.material
                  ];


            materials.forEach(
              material => {

                /*
                  程序生成与模型自带的贴图
                */

                const materialAny =
                  material as THREE.Material & {
                    map?: THREE.Texture | null;
                    normalMap?: THREE.Texture | null;
                    roughnessMap?: THREE.Texture | null;
                    metalnessMap?: THREE.Texture | null;
                    emissiveMap?: THREE.Texture | null;
                  };


                materialAny.map?.dispose();

                materialAny.normalMap?.dispose();

                materialAny.roughnessMap?.dispose();

                materialAny.metalnessMap?.dispose();

                materialAny.emissiveMap?.dispose();


                material.dispose();

              }
            );

          }

        }
      );


      roomEnvironmentTexture?.dispose();

      pmremGenerator?.dispose();

      renderer.dispose();


      if (
        mount.contains(
          renderer.domElement
        )
      ) {

        mount.removeChild(
          renderer.domElement
        );

      }

    };

  }, [
    books,
    mode,
    view,
    returnIssue,
  ]);


  /* =========================================================
     JSX
  ========================================================= */

  return (

    <div

      ref={host}

      className={

        `scene-canvas ${
          fallback
            ? `scene-fallback fallback-${mode}`
            : ""
        }`

      }

    >

      {/* ================================================
          外景替代展示画面
      ================================================ */}

      {
        fallback &&
        mode === "exterior" && (

          <img

            src={`${import.meta.env.BASE_URL}assets/ynu-library-real.png`}

            alt="云南大学图书馆"

          />

        )
      }


      {/* ================================================
          室内加载失败后备
      ================================================ */}

      {
        fallback &&
        mode === "room" && (

          <div className="fallback-reading-room">

            <div className="fallback-window left" />

            <div className="fallback-window right" />


            <div className="fallback-cabinet">

              {
                Array.from(
                  {
                    length: 30,
                  },
                  (_, index) => (

                    <i

                      key={index}

                      style={{

                        height:
                          `${
                            60 +
                            (
                              index %
                              5
                            ) *
                            6
                          }%`,

                      }}

                    />

                  )
                )
              }

            </div>


            <div className="fallback-desk" />

          </div>

        )
      }

    </div>

  );

}
