import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

/** shadcn/ui 组件的类名合并（clsx + tailwind-merge），全站唯一。 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
