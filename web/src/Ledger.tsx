/* 台账（工作区 5）——里子：表的清单、数据源与口径。
   台账是**唯一事实源**（`数据与复现/云大全学科排名、阈值动态检测表.xlsx`），
   流水线运行期只读；投喂副本是 `input/<期次>/台账.xlsx`。
   🔴 前端只读展示，绝不写台账（写入只能走 zip 级 XML 替换 + 备份，那是后端的活）。 */

import { useEffect, useState } from 'react'
import { req } from './api'
import { Icon } from './icons'

type SheetRow = { name?: string; sheet?: string; columns?: number; cols?: number; periods?: string }

/** 表清单。形状按**实测响应**写；拿不到就如实显示后端的话（不编表名）。 */
export function Ledger() {
  const [rows, setRows] = useState<SheetRow[] | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    req<{ rows?: SheetRow[]; sheets?: SheetRow[] }>('/api/ledger/sheets')
      .then((r) => { if (alive) setRows(r.rows ?? r.sheets ?? []) })
      .catch((e: { status?: number; body?: { error?: string }; message?: string }) => {
        if (alive) {
          setErr(e.body?.error ?? (e.status ? `HTTP ${e.status}` : (e.message ?? '读台账失败')))
        }
      })
    return () => { alive = false }
  }, [])

  return (
    <>
      <section className="card" style={{ padding: '22px 24px' }}>
        <h2 style={{ fontSize: 22, display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon name="doc" size={22} />台账 · 表清单
          <span className="hint" style={{ fontWeight: 400, fontSize: 14, marginLeft: 'auto' }}>
            只读
          </span>
        </h2>

        {err && (
          <div className="pending-box" style={{ marginTop: 14 }}>
            <b>后端现在读不到台账：{err}</b>
            <ul style={{ margin: '8px 0 0', paddingLeft: 20 }}>
              <li>
                它找的是 <code>input/&lt;期次&gt;/台账.xlsx</code>（投喂副本）。
                本机盘上**这两个文件是存在的**：<code>input/202607/台账.xlsx</code>、
                <code>input/202609/台账.xlsx</code>（各约 0.3 MB）。
              </li>
              <li>
                唯一事实源在 <code>数据与复现/云大全学科排名、阈值动态检测表.xlsx</code>
                （约 0.29 MB，19 个 sheet）。
              </li>
              <li>
                看起来是后端那一侧的路径/glob 没命中（Windows 下中文目录 + 相对根都可能踩），
                请后端会话核 <code>config.INPUT_DIR</code> 的实际取值。
              </li>
            </ul>
          </div>
        )}

        {!err && rows == null && <div className="pending-box" style={{ marginTop: 14 }}>正在读台账……</div>}

        {!err && rows && rows.length === 0 && (
          <div className="pending-box" style={{ marginTop: 14 }}>后端返回了空表清单。</div>
        )}

        {!err && rows && rows.length > 0 && (
          <div className="tablewrap">
          <table className="periods" style={{ marginTop: 14 }}>
            <thead>
              <tr><th>工作表</th><th>列数</th><th>期次覆盖</th></tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={(r.name ?? r.sheet ?? '') + i}>
                  <td>{r.name ?? r.sheet ?? '（未命名字段）'}</td>
                  <td className="mono">{r.columns ?? r.cols ?? '—'}</td>
                  <td className="mono">{r.periods ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </section>

      <section className="card" style={{ marginTop: 18, padding: '22px 24px' }}>
        <h2 style={{ fontSize: 19, display: 'flex', alignItems: 'center', gap: 10 }}>
          <Icon name="alert" size={20} />口径与边界（这几条是硬的）
        </h2>
        <div className="margin-note" style={{ marginTop: 14 }}>
          <div className="tag">唯一事实源</div>
          <p>
            报告里的每个数字都来自台账；台账由馆员手工维护、**按列追加**（不改历史列）。
            改台账只能走 zip 级 XML 替换 + 先备份——用 Excel 类库存盘会丢图表与条件格式。
          </p>
        </div>
        <div className="margin-note">
          <div className="tag">运行期只读</div>
          <p>
            流水线开跑与收尾各取一次台账指纹（sha256），不一致即拦停并出诊断报告。
            所以页面上的任何操作都不会写台账。
          </p>
        </div>
        <div className="margin-note">
          <div className="tag">缺数据不填假数</div>
          <p>
            台账缺列/缺数时，流水线在第一步断言闸就失败并写明「缺哪张表哪一期」，
            不会带着缺口往下跑。前端同理：拿不到就显示「未就绪」，不放占位数字。
          </p>
        </div>
      </section>
    </>
  )
}
