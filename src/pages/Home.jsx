import React from 'react';
import Box from '../components/Box';
import { bills } from '../data/bills';

export default function Home() {
  const myBills = bills.filter(b => b.tag === "For You");

  return (
    <>
      <h1 className="Title">NosPopuli</h1>
      <p className="read-the-docs">Legislation for the People. Understood by the People.</p>

      <h2 className="subheading">Current Bills</h2>
      <div className="scroll-container">
        <div className="bill-row">
          {bills.map((bill, index) => (
            <Box key={index} title={bill.title} party={bill.party} />
          ))}
        </div>
      </div>

      <h2 className="subheading">For You</h2>
      <div className="scroll-container">
        <div className="bill-row">
          {myBills.map((bill, i) => (
            <Box
              key={i}
              title={bill.title}
              party={bill.party}
              style={{ borderColor: '#FFD700', boxShadow: '0 0 8px #FFD700' }}
            />
          ))}
        </div>
      </div>
    </>
  );
}