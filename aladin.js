var aladin;
A.init.then(() => {
    aladin = A.aladin('#aladin-lite-div', { fov: 1, survey: 'hips/F658N/' });
});
