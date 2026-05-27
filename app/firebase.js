import { initializeApp } from 'firebase/app';
import { getDatabase } from 'firebase/database';
import { getAuth, signInAnonymously } from 'firebase/auth';

const firebaseConfig = {
  apiKey: "AIzaSyAJewDTn21UBdteXwjF97S3sabz4Ya9zOo",
  authDomain: "dog-door-632e6.firebaseapp.com",
  databaseURL: "https://dog-door-632e6-default-rtdb.firebaseio.com",
  projectId: "dog-door-632e6",
  storageBucket: "dog-door-632e6.firebasestorage.app",
  messagingSenderId: "836002977906",
  appId: "1:836002977906:web:0e43fa2b1f96d178e34aeb"
};

const app = initializeApp(firebaseConfig);
export const db = getDatabase(app);
export const auth = getAuth(app);

signInAnonymously(auth).catch(e => console.warn('Firebase auth failed:', e));
