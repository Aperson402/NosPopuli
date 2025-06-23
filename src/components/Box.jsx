import React from 'react';
import './Box.css'; // optional if you want to separate styles

const getColor = (party) => {
  if (party === "d") return "#3b82f6";
  if (party === "r") return "#ef4444";
  if (party === "m") return "#8b5cf6";
  return "#f0f0f0";
};

export default function Box({ title, party, style = {} }) {
  return (
    <div className="box" style={{ backgroundColor: getColor(party), ...style }}>
      {title}
    </div>
  );
}