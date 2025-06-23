import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom'
import './App.css'

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

/**
 * Maps party abbreviations to their corresponding colors
 * @param {string} party - Party abbreviation ('d' = Democrat, 'r' = Republican, 'm' = Mixed/Independent)
 * @returns {string} Hex color code for the party
 * 
 * TODO: Consider moving this to a constants file when refactoring
 * TODO: Add more parties or make this configurable
 */
const getColor = (party) => {
  if (party === "d") return "#3b82f6"; // Blue for Democrats
  if (party === "r") return "#ef4444"; // Red for Republicans  
  if (party === "m") return "#8b5cf6"; // Purple for Mixed/Independent
  return "#f0f0f0"; // Default gray for unknown parties
};

// =============================================================================
// REUSABLE COMPONENTS
// =============================================================================

/**
 * Individual bill/topic display component
 * @param {string} title - Display name for the bill
 * @param {string} party - Party affiliation ('d', 'r', 'm')
 * @param {object} style - Additional CSS styles to apply
 * 
 * TODO: Expand this to include more bill metadata (date, status, description)
 * TODO: Add click handler for bill details
 * TODO: Consider renaming to 'BillCard' for clarity
 */
function Box({ title, party, style }) {
  return (
    <div
      className="box"
      style={{ color: getColor(party), backgroundColor: 'transparent', ...style }}
    >
      {title}
    </div>
  );
}

/**
 * Navigation bar component with search and routing
 * Dynamically changes button text based on current page
 * 
 * TODO: Implement search functionality
 * TODO: Add user authentication/profile
 * TODO: Make search actually filter bills
 */
function TopBar() {
  const location = useLocation();
  const isHome = location.pathname === '/';

  return (
    <div className="top-bar">
      <div className="left-side">
        {/* TODO: Connect this search to actual filtering logic */}
        <input type="text" placeholder="Search..." className="search-bar" />
      </div>
      <div className="right-side">
        {/* Dynamic routing button - shows "Discover" on home, "Home" elsewhere */}
        <Link to={isHome ? "/discover" : "/"}>
          <button>{isHome ? "Discover" : "Home"}</button>
        </Link>
        {/* TODO: Implement these features */}
        <button>Bill Reviews</button>
        <button>Settings</button>
        <button>Favorite Senators</button>
      </div>
    </div>
  );
}

// =============================================================================
// DATA - Move this to a separate file/API when scaling
// =============================================================================

/**
 * Mock bill data for MVP
 * Each bill has: title, party affiliation, and optional tag for categorization
 * 
 * TODO: Replace with real legislative data from Congress API
 * TODO: Add more metadata: description, status, sponsor, date, etc.
 * TODO: Consider using a proper data structure or database
 */
const bills = [
  { title: "Freedom to Vote Act", party: "d", tag: "Discover" },
  { title: "Protecting Medicare and American Farmers from Sequester Cuts Act", party: "d" },
  { title: "Born-Alive Abortion Survivors Protection Act", party: "r", tag: "Discover" },
  { title: "Equality Act", party: "d", tag: "For You" },
  { title: "Secure the Border Act of 2023", party: "r", tag: "For You" },
  { title: "Restricting the Use of TikTok on Government Devices Act", party: "r" },
  { title: "No TikTok on United States Devices Act", party: "d" },
  { title: "Inflation Reduction Act of 2022", party: "d", tag: "Discover" },
  { title: "Parents Bill of Rights Act", party: "r", tag: "Discover" },
  { title: "Affordable Insulin Now Act", party: "d", tag: "For You" },
  { title: "Protecting Our Kids Act", party: "d" },
  { title: "Right to Contraception Act", party: "d" },
  { title: "SAFE Banking Act of 2023", party: "m", tag: "Discover" }, // bipartisan
  { title: "RESTRICT Act", party: "m", tag: "For You" }, // bipartisan
  { title: "John R. Lewis Voting Rights Advancement Act", party: "d" },
];

/**
 * Hot topics for the Discover page
 * TODO: Make this dynamic based on trending bills
 * TODO: Link topics to actual bills
 */
const topics = [
  "Abortion Rights",
  "Gun Control", 
  "Climate Change",
  "AI Regulation",
  "Voting Access",
  "Immigration Reform",
  "Healthcare Expansion",
  "Student Debt Forgiveness",
  "Police Reform",
  "Tax Policy",
];

/**
 * Color palette for topic boxes
 * Cycles through colors to ensure visual variety
 * TODO: Consider using a more sophisticated color generation system
 */
const topicColors = [
  "#ef4444", // red
  "#3b82f6", // blue
  "#10b981", // green
  "#f59e0b", // amber
  "#8b5cf6", // purple
  "#ec4899", // pink
  "#14b8a6", // teal
  "#f97316", // orange
  "#6366f1", // indigo
  "#22c55e", // lime
];

// =============================================================================
// PAGE COMPONENTS
// =============================================================================

/**
 * Home page component - shows all bills and personalized "For You" section
 * Core value: Quick overview of current legislation + personalization
 * 
 * TODO: Add filtering options (by party, date, status)
 * TODO: Make "For You" algorithm more sophisticated
 * TODO: Add bill status indicators
 */
const Home = () => {
  // Filter bills tagged as personalized recommendations
  const myBills = bills.filter(b => b.tag === "For You");

  return (
    <>
      <h1 className="Title">NosPopuli</h1>
      <p className="read-the-docs">
        Legislation for the People. Understood by the People.
      </p>

      {/* All current bills section */}
      <h2 className="subheading">Current Bills</h2>
      <div className="scroll-container">
        <div className="bill-row">
          {bills.map((bill, index) => (
            <Box key={index} title={bill.title} party={bill.party} />
          ))}
        </div>
      </div>

      {/* Personalized recommendations with special styling */}
      <h2 className="subheading">For You</h2>
      <div className="scroll-container">
        <div className="bill-row">
          {myBills.map((bill, i) => (
            <Box
              key={i}
              title={bill.title}
              party={bill.party}
              // Gold highlight for personalized bills
              style={{ borderColor: '#FFD700', boxShadow: '0 0 8px #FFD700' }}
            />
          ))}
        </div>
      </div>
    </>
  );
};

/**
 * Discovery page component - helps users explore trending legislation
 * Core value: Surfacing important bills users might miss + topic exploration
 * 
 * TODO: Add filtering by topic
 * TODO: Make topic boxes clickable to show related bills
 * TODO: Add trending/popularity indicators
 */
const Discover = () => {
  // Filter bills tagged for discovery
  const discoverBills = bills.filter(b => b.tag === "Discover");

  return (
    <>
      <h1 className="Title">Discover Bills</h1>
      <p className="read-the-docs">
        Explore trending legislation across all parties.
      </p>
      
      {/* Curated discovery bills */}
      <div className="scroll-container">
        <div className="bill-row">
          {discoverBills.map((bill, index) => (
            <Box key={index} title={bill.title} party={bill.party} />
          ))}
        </div>
      </div>
      
      {/* Topic exploration grid */}
      <h2 className="subheading">Hot Topics</h2>
      <div className="topic-grid">
        {topics.map((topic, index) => (
          <div
            key={index}
            className="topic-box"
            // Cycle through colors using modulo
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

/**
 * Root application component with routing
 * 
 * ARCHITECTURE NOTES FOR REFACTORING:
 * - Consider moving TopBar outside Routes for consistency
 * - Add error boundary for production
 * - Consider adding loading states
 * - Add 404 page handling
 * 
 * SUGGESTED FILE STRUCTURE FOR REFACTOR:
 * /src
 *   /components
 *     - TopBar.jsx
 *     - BillCard.jsx (rename Box)
 *     - TopicCard.jsx
 *   /pages  
 *     - Home.jsx
 *     - Discover.jsx
 *   /utils
 *     - colors.js (getColor function)
 *   /data
 *     - bills.js
 *     - topics.js
 *   /hooks (for future)
 *     - useBills.js
 *     - useSearch.js
 */
function App() {
  return (
    <Router>
      <TopBar />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/discover" element={<Discover />} />
        {/* TODO: Add routes for:
            - /bill/:id (individual bill details)
            - /topic/:name (bills by topic)
            - /settings (user preferences)
            - /favorites (saved bills)
        */}
      </Routes>
    </Router>
  );
}

export default App;