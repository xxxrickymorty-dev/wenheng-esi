import * as THREE from "three";

    /* =======================================================
       Camera

       以后如果只想调“室内中庭”的默认视角，
       只改下面 ROOM_CAMERA_* 这 3 组参数即可。
       外景参数完全独立，不会再混在一起。
    ======================================================= */

export const ROOM_CAMERA_FOV = 46;

export const ROOM_CAMERA_POSITION =
      new THREE.Vector3(
        2.8,
        2.15,
        11.8
      );

export const ROOM_CAMERA_TARGET =
      new THREE.Vector3(
        0,
        2.8,
        0
      );




/** 馆藏展厅相机（2026-10-01 从 LibraryScene 抽出）：外景/内景两套机位。
    ROOM_CAMERA_* 导出给归架动画与重置视角复用；行为与拆分前一致。 */
export function createLibraryCamera(
  mode: "exterior" | "room",
  view: "front" | "aerial",
) {
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



  return { camera, origin, target };
}
