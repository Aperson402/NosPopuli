import React from 'react';
import './TopicBox.css'; // optional

export default function TopicBox({ topic, color }) {
  return (
    <div className="topic-box">
      <div className="color-band" style={{ backgroundColor: color }}></div>
      <span>{topic}</span>
    </div>
  );
}