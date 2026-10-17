import { useState } from "react";
import { TopBar, StatusBand, PageFoot, Palette } from "./components/shell";
import { OutReport } from "./screens/OutReport";
import { AcquireCheck } from "./screens/AcquireCheck";
import { VerifyFinal } from "./screens/VerifyFinal";

type ScreenId = "hub" | "acquire" | "verify";

export default function App() {
  const [screen, setScreen] = useState<ScreenId>("hub");

  return (
    <>
      <TopBar
        current={screen === "hub" ? "acquire" : screen === "verify" ? "verify" : "acquire"}
        onGo={(id) => {
          if (id === "acquire") setScreen("acquire");
          else if (id === "verify") setScreen("verify");
          else setScreen("hub");
        }}
        right={
          <>
            <button
              onClick={() => setScreen("hub")}
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

      {screen === "hub" && (
        <>
          <StatusBand task="已完成" sign="未签发" right="第 39 期　·　2 0 2 6 0 9" />
        </>
      )}

      <PageFoot
        left="雲 南 大 學 圖 書 館 · 學 科 信 息 參 考"
        right="并 行 实 验　·　随 时 可 能 删 除"
      />
    </>
  );
}
