import React from 'react';

export interface TabDef {
  id: string;
  label: string;
}

export interface TabBarProps {
  tabs: TabDef[];
  active: string;
  onSelect: (id: string) => void;
}

/** A simple horizontal tab strip. Accessible: role=tablist + aria-selected. */
export function TabBar({ tabs, active, onSelect }: TabBarProps): React.ReactElement {
  return (
    <div className="tabbar" role="tablist">
      {tabs.map((tab) => {
        const isActive = tab.id === active;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={isActive ? 'tab tab--active' : 'tab'}
            onClick={() => onSelect(tab.id)}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

export default TabBar;
