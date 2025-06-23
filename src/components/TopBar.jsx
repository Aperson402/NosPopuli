import React from 'react';
import { Link, useLocation } from 'react-router-dom';

export default function TopBar() {
  const location = useLocation();
  const isHome = location.pathname === '/';

  return (
    <div className="top-bar">
      <div className="left-side">
        <input type="text" placeholder="Search..." className="search-bar" />
      </div>
      <div className="right-side">
        <Link to={isHome ? "/discover" : "/"}>
          <button>{isHome ? "Discover" : "Home"}</button>
        </Link>
        <button>Bill Reviews</button>
        <button>Settings</button>
        <button>Favorite Senators</button>
      </div>
    </div>
  );
}