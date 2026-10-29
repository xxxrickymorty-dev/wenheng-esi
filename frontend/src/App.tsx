import { useState } from "react";
import { TopBar, StatusBand, PageFoot, Palette } from "./components/shell";
import { OutReport } from "./screens/OutReport";
import { AcquireCheck } from "./screens/AcquireCheck";
import { VerifyFinal } from "./screens/VerifyFinal";
import { ShelfStair } from "./screens/ShelfStair";
import { WorkbenchSpread } from "./screens/WorkbenchSpread";

type ScreenId = "spread" | "hub" | "acquire" | "verify" | "shelf";

/** 带 #shelf / #hub 之类就按它开；什么都没写，默认进跨页双联工作台壳
    （rick 2026-10-25：整个工作台改成这个，先在 lab 看效果）。 */
function initialScreen(): ScreenId {
  const h = location.hash.replace("#", "");
  return h === "hub" || h === "acquire" || h === "verify" || h === "shelf" ? h : "spread";
}

export default function App() {
  const [screen, setScreen] = useState<ScreenId>(initialScreen);

  /** 切屏顺手写进地址，刷新还停在原处。 */
  const go = (s: ScreenId) => {
    setScreen(s);
    history.replaceState(null, "", `#${s}`);
  };

  /* 跨页壳自带左栏导航与 100dvh 版式，不套 lab 顶栏/页脚。 */
  if (screen === "spread") return <WorkbenchSpread />;

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
              className="font-kai text-[13px] tracking-[.22em] text-pine-50 hover:text-white"
            >
              陈 列 馆 ↗
            </button>
            <button
              onClick={() => go("hub")}
              className="font-kai text-[13px] tracking-[.22em] text-pine-50 hover:text-white"
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
