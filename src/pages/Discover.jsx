import React from 'react';
import Box from '../components/Box';
import TopicBox from '../components/TopicBox';
import { bills } from '../data/bills';
import { topics, topicColors } from '../data/topics';

export default function Discover() {
  const discoverBills = bills.filter(b => b.tag === "Discover");
  const newBills = [
    { title: "New Bill A", party: "d" },
    { title: "New Bill B", party: "r" },
    { title: "New Bill C", party: "m" },
    { title: "New Bill D", party: "d" },
  ];

  return (
    <>
      <h1 className="Title">Discover</h1>
      <p className="read-the-docs">
        Explore new and trending legislation across all parties.
      </p>

      <h2 className="subheading">New Bills</h2>
      <div className="scroll-container">
        <div className="bill-row">
          {newBills.map((bill, index) => (
            <Box key={index} title={bill.title} party={bill.party} />
          ))}
        </div>
      </div>

      <h2 className="subheading">Hot Topics</h2>
      <div className="topic-grid">
        {topics.map((topic, index) => (
          <TopicBox
            key={index}
            topic={topic}
            color={topicColors[index % topicColors.length]}
          />
        ))}
      </div>

      <h2 className="subheading">Trending Bills</h2>
      <div className="scroll-container">
        <div className="bill-row">
          {discoverBills.map((bill, index) => (
            <Box key={index} title={bill.title} party={bill.party} />
          ))}
        </div>
      </div>
    </>
  );
}