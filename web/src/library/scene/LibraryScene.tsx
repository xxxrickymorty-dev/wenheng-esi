"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { buildLibraryArchitecture } from "./architecture";
import { createLibraryCamera, ROOM_CAMERA_FOV, ROOM_CAMERA_POSITION, ROOM_CAMERA_TARGET } from "./libraryCamera";
import { setupLibraryLights } from "./libraryLights";
import { createCoverTexture } from "./coverTexture";
import { createLibraryRuntime, type ReportBook } from "./libraryRuntime";
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


    /* Camera → libraryCamera.ts（2026-10-01 拆分） */

    const { camera, origin, target } =
      createLibraryCamera(mode, view);

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


    /* Lights → libraryLights.ts（2026-10-01 拆分） */

    setupLibraryLights(scene, mode);

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

    /* Canvas 封面纹理 → coverTexture.ts（2026-10-01 拆分） */

    /* =======================================================
       可点击馆藏

       按安全预览提供的馆藏封面陈列书册；
       场景不读取报告正文或数值。
       同一边馆藏较多时自动横向排开并缩小，避免重叠。
    ======================================================= */

    const picks:
      THREE.Object3D[] = [];


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
                    createCoverTexture(
                      [
                        "学科信息参考",
                        `总第 ${item.no} 期`,
                        item.period,
                      ],
                      "#193f33",
                      "#e4d9b9",
                      renderer.capabilities.getMaxAnisotropy(),
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


    /* 交互 / 主循环 / 资源释放 → libraryRuntime.ts（2026-10-01 拆分） */

    const runtime =
      createLibraryRuntime({
        mount, scene, camera, renderer, reportBooks, picks, origin, target,
        mode, enteringRef, entryStart, motionRef, pick, takeStartRef,
        returnIssue, returnCompleteRef,
        ROOM_CAMERA_FOV, ROOM_CAMERA_POSITION, ROOM_CAMERA_TARGET,
        roomEnvironmentTexture, pmremGenerator,
      });


    return () => {

      disposed =
        true;

      runtime.dispose();

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

            width={1280}

            height={720}

            decoding="async"

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
