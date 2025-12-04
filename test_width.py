import streamlit as st
import pandas as pd

st.write("Testing width=True")
df = pd.DataFrame({'col1': [1, 2], 'col2': [3, 4]})
try:
    st.dataframe(df, width=True)
    st.write("Success")
except Exception as e:
    st.write(f"Error: {e}")
