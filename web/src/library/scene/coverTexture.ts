import * as THREE from "three";

/** 馆藏封面 Canvas 纹理（2026-10-01 从 LibraryScene 抽出）：
    深墨绿布纹 + 金色双线 + 校园线稿；纯函数，唯一输入是文字与各向异性上限。 */
    /* =======================================================
       Canvas 封面纹理
    ======================================================= */

export function createCoverTexture(

      lines: string[],

      _bg: string,

      _fg: string,

      maxAnisotropy: number,

      width = 512,

      height = 640

    ): THREE.CanvasTexture {

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
          maxAnisotropy
        );

      texture.needsUpdate =
        true;

      return texture;

    };


