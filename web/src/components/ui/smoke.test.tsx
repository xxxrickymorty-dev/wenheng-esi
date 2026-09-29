import { renderToString } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { Button } from "./button"
import { Table, TableBody, TableCell, TableRow } from "./table"

/** shadcn/ui 件的冒烟测试：能渲染、类名走 cva/cn 链路、样式变量由 index.css 桥接。 */
describe("shadcn/ui 件", () => {
  it("Button 渲染文字与变体类", () => {
    const html = renderToString(<Button variant="destructive">危险操作</Button>)
    expect(html).toContain("危险操作")
    expect(html).toContain("bg-destructive")
  })

  it("Table 渲染结构", () => {
    const html = renderToString(
      <Table>
        <TableBody>
          <TableRow>
            <TableCell>单元格</TableCell>
          </TableRow>
        </TableBody>
      </Table>,
    )
    expect(html).toContain("单元格")
    expect(html).toContain("<table")
  })
})
