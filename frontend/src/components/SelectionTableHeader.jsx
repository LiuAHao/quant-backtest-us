import React from "react";

export function SelectionTableHeader({ checked, disabled = false, onToggle }) {
  return (
    <label className="table-checkbox">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={onToggle} />
      <span>选择</span>
    </label>
  );
}
