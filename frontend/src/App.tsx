import { useState } from "react";
import { TopBar, StatusBand, PageFoot, Palette } from "./components/shell";
import { OutReport } from "./screens/OutReport";
import { AcquireCheck } from "./screens/AcquireCheck";
import { VerifyFinal } from "./screens/VerifyFinal";
import { ShelfStair } from "./screens/ShelfStair";

type ScreenId = "hub" | "acquire" | "verify" | "shelf";

/** 带 #shelf / #hub 之类就按它开；什么都没写，默认进陈列馆（实验目录现在只做这一屏）。 */
function initialScreen(): ScreenId {
  const h = location.hash.replace("#", "");
  return h === "hub" || h === "acquire" || h === "verify" ? h : "shelf";
}

export default function App() {
  const [screen, setScreen] = useState<ScreenId>(initialScreen);

  /** 切屏顺手写进地址，刷新还停在原处。 */
  const go = (s: ScreenId) => {
    setScreen(s);
    history.replaceState(null, "", `#${s}`);
  };

  return (
    <>
      <TopBar
        current={screen === "hub" ? "acquire" : screen === "verify" ? "verify" : "acquire"}
        onGo={(id) => {
          if (id === "acquire") go("acquire");
          else if (id === "verify") go("verify");
          else go("hub");
        }}
        right={
          <>
            <button
              onClick={() => go("shelf")}
              className="font-kai text-[11px] tracking-[.22em] text-sea-50/70 hover:text-sea-50"
            >
              陈 列 馆 ↗
            </button>
            <button
              onClick={() => go("hub")}
              className="font-kai text-[11px] tracking-[.22em] text-sea-50/70 hover:text-sea-50"
            >
              出 报 告 ↖
            </button>
            <Palette />
          </>
        }
      />

      {screen === "hub" && <OutReport />}
      {screen === "acquire" && <AcquireCheck />}
      {screen === "verify" && <VerifyFinal />}
      {screen === "shelf" && <ShelfStair />}

      {screen === "hub" && (
        <>
          <StatusBand task="已完成" sign="未签发" right="第 39 期　·　2 0 2 6 0 9" />
        </>
      )}

      {screen !== "shelf" && (
        <PageFoot
          left="雲 南 大 學 圖 書 館 · 學 科 信 息 參 考"
          right="并 行 实 验　·　随 时 可 能 删 除"
        />
      )}
    </>
  );
}
