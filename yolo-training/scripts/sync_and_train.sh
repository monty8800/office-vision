#!/bin/bash
# 把监控页「数据集标注」收集的帧+labelme JSON 同步到 Windows 训练机，并触发重训。
#
# 流程：VM115(agent.data/annotate) → 本机临时目录 → Windows(datasets/cigarette/annotate)
#       → Windows 上 labelme2yolo.py → train_cigarette.py --finetune
#
# 用法（在 Mac 管理机执行）：
#   WIN_PASS='<dsh密码>' bash scripts/sync_and_train.sh
#   # 只同步不训练： SYNC_ONLY=1 bash scripts/sync_and_train.sh
#
# 需预置：
#   ~/.ssh/pve_192.168.9.115   VM115 密钥（root@192.168.9.214）
#   sshpass                   用于 Windows 密码登录（dsh@192.168.9.204）

set -euo pipefail

VM="root@192.168.9.214"
WIN_USER="dsh"
WIN_IP="192.168.9.204"
WIN_PASS="${WIN_PASS:?需设置 WIN_PASS=dsh密码}"
STAGE="$(mktemp -d)"
ANNO_REMOTE="/opt/office-vision/office-vision-agent/data/annotate"
WIN_REPO="C:/Users/dsh/office-vision-training/office-vision/yolo-training"
WIN_DATA="${WIN_REPO}/datasets/cigarette/annotate"

SSH_VM=(ssh -i ~/.ssh/pve_192.168.9.115 -o StrictHostKeyChecking=accept-new)
SCP_VM=(scp -i ~/.ssh/pve_192.168.9.115 -o StrictHostKeyChecking=accept-new)
SSH_WIN=(sshpass -p "$WIN_PASS" ssh -o StrictHostKeyChecking=accept-new "${WIN_USER}@${WIN_IP}")
SCP_WIN=(sshpass -p "$WIN_PASS" scp -o StrictHostKeyChecking=accept-new)

echo "== 1) 拉取 VM115 标注到本地 → ${STAGE}"
"${SCP_VM[@]}" -r "${VM}:${ANNO_REMOTE}" "${STAGE}/" 2>/dev/null || true
echo "   标注数：$(find "${STAGE}" -name '*.json' 2>/dev/null | wc -l | tr -d ' ') 条"

echo "== 2) 推送标注到 Windows ${WIN_DATA}"
for sub in smoking normal; do
  if [ -d "${STAGE}/annotate/${sub}" ] && [ -n "$(ls -A "${STAGE}/annotate/${sub}" 2>/dev/null)" ]; then
    "${SSH_WIN[@]}" "if not exist \"${WIN_DATA}\\${sub}\" mkdir \"${WIN_DATA}\\${sub}\"" 2>/dev/null || true
    "${SCP_WIN[@]}" "${STAGE}/annotate/${sub}"/*.* "${WIN_USER}@${WIN_IP}:${WIN_DATA}/${sub}/" 2>/dev/null || true
  fi
done
echo "   已推送。Windows 现有 smoking=$(sshpass -p "$WIN_PASS" ssh -o StrictHostKeyChecking=accept-new "${WIN_USER}@${WIN_IP}" "dir /b \"${WIN_DATA}\\smoking\\*.json\" 2>nul | find /c /v \"\"" 2>/dev/null || echo 0) 条 / normal=$(sshpass -p "$WIN_PASS" ssh -o StrictHostKeyChecking=accept-new "${WIN_USER}@${WIN_IP}" "dir /b \"${WIN_DATA}\\normal\\*.json\" 2>nul | find /c /v \"\"" 2>/dev/null || echo 0) 条"

# == 同步完成：确认数据已落 Windows 后，清空 VM115 上的标注帧，节省服务器资源 ==
# 只在确认源已全部同步到 Windows 时才删除，避免丢数据；KEEP_VM_ANNOT=1 可跳过。
echo "== 2b) 清理 VM115 标注（同步完成后）=="
SRC_N=$(find "${STAGE}/annotate" -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
WIN_N=$(sshpass -p "$WIN_PASS" ssh -o StrictHostKeyChecking=accept-new "${WIN_USER}@${WIN_IP}" "dir /b /s \"${WIN_DATA}\\*.json\" 2>nul | find /c /v \"\"" 2>/dev/null || echo 0)
if [ "${KEEP_VM_ANNOT:-0}" = "1" ]; then
  echo "   [跳过] 已设置 KEEP_VM_ANNOT=1，保留 VM115 标注。"
elif [ "${WIN_N:-0}" -ge "${SRC_N:-0}" ] && [ "${SRC_N:-0}" -gt 0 ]; then
  "${SSH_VM[@]}" "rm -rf '${ANNO_REMOTE}' && mkdir -p '${ANNO_REMOTE}/smoking' '${ANNO_REMOTE}/normal'" 2>/dev/null || true
  echo "   已清理 VM115 ${ANNO_REMOTE}（源=${SRC_N} / 窗口=${WIN_N}），标注帧删除，节省磁盘。"
else
  echo "   [跳过清理] 同步未确认（源=${SRC_N} / 窗口=${WIN_N}; KEEP_VM_ANNOT 未设），保留 VM115 标注以防丢失。"
fi

if [ "${SYNC_ONLY:-0}" = "1" ]; then
  echo "== 仅同步（跳过训练）。清理临时目录。"
  rm -rf "$STAGE"
  exit 0
fi

echo "== 3) Windows 上转换 + 重训（CPU/GPU 自动）=="
"${SSH_WIN[@]}" "cd ${WIN_REPO} && C:\\Users\\dsh\\office-vision-training\\.venv\\Scripts\\python.exe scripts\\labelme2yolo.py > C:\\Users\\dsh\\office-vision-training\\train.log 2>&1 && C:\\Users\\dsh\\office-vision-training\\.venv\\Scripts\\python.exe scripts\\train_cigarette.py --finetune --epochs 100 --imgsz 640 --batch 16 >> C:\\Users\\dsh\\office-vision-training\\train.log 2>&1; echo TRAIN_EXIT=$?"
echo "   训练日志：Windows C:\\Users\\dsh\\office-vision-training\\train.log"
rm -rf "$STAGE"
echo "== 完成。训练产出 best.pt 后复制回部署：runs/detect/cigarette/weights/best.pt → weights/cigarette-best.pt =="
