import * as THREE from "three";

/** 展厅运行时（2026-10-01 从 LibraryScene 抽出）：相机轨道与指针交互、
    取书/归架镜头动画、逐帧渲染循环、窗口尺寸与资源释放。
    与拆分前行为一致（拆分后渲染截图逐像素验收，差 0）。 */

type Ref<T> = { current: T };

export type ReportBook = {
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

type RuntimeDeps = {
  mount: HTMLDivElement;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  reportBooks: Array<ReportBook | undefined>;
  picks: THREE.Object3D[];
  origin: THREE.Vector3;
  target: THREE.Vector3;
  mode: "exterior" | "room";
  enteringRef: Ref<boolean>;
  entryStart: Ref<number>;
  motionRef: Ref<boolean>;
  pick: Ref<(index: number) => void>;
  takeStartRef: Ref<((index: number) => void) | undefined>;
  returnIssue: number | null;
  returnCompleteRef: Ref<(() => void) | undefined>;
  ROOM_CAMERA_FOV: number;
  ROOM_CAMERA_POSITION: THREE.Vector3;
  ROOM_CAMERA_TARGET: THREE.Vector3;
  roomEnvironmentTexture: THREE.Texture | null;
  pmremGenerator: THREE.PMREMGenerator | null;
};

export function createLibraryRuntime(deps: RuntimeDeps) {
  const {
    mount, scene, camera, renderer, reportBooks, picks, origin, target, mode,
    enteringRef, entryStart, motionRef, pick, takeStartRef, returnIssue,
    returnCompleteRef, ROOM_CAMERA_FOV, ROOM_CAMERA_POSITION, ROOM_CAMERA_TARGET,
    roomEnvironmentTexture, pmremGenerator,
  } = deps;

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

    const dispose = () => {
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

  return { dispose };
}
