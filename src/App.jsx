import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom';
import './App.css';

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

/**
 * Maps party abbreviations to their corresponding colors using CSS variables.
 * @param {string} party - Party abbreviation ('d' = Democrat, 'r' = Republican, 'm' = Mixed/Independent)
 * @returns {string} CSS variable name for the party color.
 */
const getPartyColorVar = (party) => {
  if (party === "d") return "var(--accent-color-blue)";
  if (party === "r") return "var(--accent-color-red)";
  if (party === "m") return "var(--accent-color-purple)";
  return "var(--text-color-secondary)"; // Default gray for unknown parties
};

// =============================================================================
// REUSABLE COMPONENTS
// =============================================================================

/**
 * Individual bill/topic display component (renamed to BillCard for clarity).
 * @param {string} title - Display name for the bill.
 * @param {string} party - Party affiliation ('d', 'r', 'm').
 * @param {object} style - Additional CSS styles to apply.
 * @param {function} onClick - Click handler for the card.
 */
function BillCard({ title, party, style, onClick }) {
  return (
    <div
      className="box"
      style={{ '--party-color': getPartyColorVar(party), ...style }}
      onClick={onClick}
    >
      <div className="box-content">
        <div className="box-image-placeholder"></div> {/* Placeholder for image/icon */}
        <h3 className="box-title">{title}</h3>
        {/* Potentially add more details here */}
      </div>
    </div>
  );
}

/**
 * Navigation bar component with search and routing.
 * Dynamically changes button text based on current page.
 */
function TopBar() {
  const location = useLocation();
  const isHome = location.pathname === '/';

  return (
    <div className="top-bar">
      <div className="left-side">
        <input type="text" placeholder="Search bills, topics, senators..." className="search-bar" />
      </div>
      <div className="right-side">
        <Link to="/">
          <button className="nav-button">Home</button>
        </Link>
        <Link to="/discover">
          <button className="nav-button">Discover</button>
        </Link>
        <button className="nav-button">Bill Reviews</button>
        <button className="nav-button">Settings</button>
        <button className="nav-button">Favorite Senators</button>
      </div>
    </div>
  );
}

// =============================================================================
// DATA - Moved to separate files for better organization
// =============================================================================

// (Assuming bills, topics, and topicColors are now imported from src/data/bills.js and src/data/topics.js)
// For now, keeping them here for direct reference as per previous structure.
const bills = [
  { id: '1', title: "Freedom to Vote Act", party: "d", tag: "Discover" },
  { id: '2', title: "Protecting Medicare and American Farmers from Sequester Cuts Act", party: "d" },
  { id: '3', title: "Born-Alive Abortion Survivors Protection Act", party: "r", tag: "Discover" },
  { id: '4', title: "Equality Act", party: "d", tag: "For You" },
  { id: '5', title: "Secure the Border Act of 2023", party: "r", tag: "For You" },
  { id: '6', title: "Restricting the Use of TikTok on Government Devices Act", party: "r" },
  { id: '7', title: "No TikTok on United States Devices Act", party: "d" },
  { id: '8', title: "Inflation Reduction Act of 2022", party: "d", tag: "Discover" },
  { id: '9', title: "Parents Bill of Rights Act", party: "r", tag: "Discover" },
  { id: '10', title: "Affordable Insulin Now Act", party: "d", tag: "For You" },
  { id: '11', title: "Protecting Our Kids Act", party: "d" },
  { id: '12', title: "Right to Contraception Act", party: "d" },
  { id: '13', title: "SAFE Banking Act of 2023", party: "m", tag: "Discover" }, // bipartisan
  { id: '14', title: "RESTRICT Act", party: "m", tag: "For You" }, // bipartisan
  { id: '15', title: "John R. Lewis Voting Rights Advancement Act", party: "d" },
];

const topics = [
  "Abortion Rights", "Gun Control", "Climate Change", "AI Regulation",
  "Voting Access", "Immigration Reform", "Healthcare Expansion",
  "Student Debt Forgiveness", "Police Reform", "Tax Policy",
];

const topicColors = [
  "var(--accent-color-red)", "var(--accent-color-blue)", "var(--accent-color-green)",
  "var(--accent-color-amber)", "var(--accent-color-purple)", "var(--accent-color-pink)",
  "var(--accent-color-teal)", "var(--accent-color-orange)", "var(--accent-color-indigo)",
  "var(--accent-color-lime)",
];


// =============================================================================
// PAGE COMPONENTS
// =============================================================================

/**
 * Home page component - shows all bills and personalized "For You" section.
 */
const Home = () => {
  const myBills = bills.filter(b => b.tag === "For You");

  return (
    <>
      <h1 className="Title">NosPopuli</h1>
      <p className="read-the-docs">
        Legislation for the People. Understood by the People.
      </p>

      <h2 className="section-title">Current Bills</h2>
      <div className="scroll-container">
        <div className="bill-row">
          {bills.map((bill) => (
            <BillCard key={bill.id} title={bill.title} party={bill.party} />
          ))}
        </div>
      </div>

      <h2 className="section-title">For You</h2>
      <div className="scroll-container">
        <div className="bill-row">
          {myBills.map((bill) => (
            <BillCard
              key={bill.id}
              title={bill.title}
              party={bill.party}
              style={{ border: '2px solid var(--accent-color-gold)', boxShadow: '0 0 10px var(--accent-color-gold)' }}
            />
          ))}
        </div>
      </div>
    </>
  );
};

/**
 * Discovery page component - helps users explore trending legislation.
 */
const Discover = () => {
  const discoverBills = bills.filter(b => b.tag === "Discover");

  return (
    <>
      <h1 className="Title">Discover Bills</h1>
      <p className="read-the-docs">
        Explore trending legislation across all parties.
      </p>
      
      <h2 className="section-title">Trending Bills</h2>
      <div className="scroll-container">
        <div className="bill-row">
          {discoverBills.map((bill) => (
            <BillCard key={bill.id} title={bill.title} party={bill.party} />
          ))}
        </div>
      </div>
      
      <h2 className="section-title">Hot Topics</h2>
      <div className="topic-grid">
        {topics.map((topic, index) => (
          <div
            key={index}
            className="topic-box"
            style={{ "--band-color": topicColors[index % topicColors.length] }}
          >
            {topic}
          </div>
        ))}
      </div>
    </>
  );
};

// =============================================================================
// MAIN APP COMPONENT
// =============================================================================

function App() {
  return (
    <Router>
      <TopBar />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/discover" element={<Discover />} />
        {/* Future routes */}
      </Routes>
    </Router>
  );
}

export default App;