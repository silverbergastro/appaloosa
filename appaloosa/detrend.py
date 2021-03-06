'''
Use this file to keep various detrending methods

'''
import numpy as np
#from pandas import rolling_median #, rolling_mean, rolling_std, rolling_skew
import pandas as pd
from scipy.optimize import curve_fit
from gatspy.periodic import LombScargleFast
from gatspy.periodic import SuperSmoother
# import pywt
from scipy import signal
from scipy.interpolate import LSQUnivariateSpline, UnivariateSpline
import matplotlib.pyplot as plt


def rolling_poly(time, flux, error, order=3, window=0.5):
    '''
    Fit polynomials in a sliding window. Not very efficient, likely ignoring much
    better functions on how to smooth.

    Name convention meant to match the pandas rolling_ stats

    Parameters
    ----------
    time : 1-d numpy array
    flux : 1-d numpy array
    error : 1-d numpy array
    order : int, optional
    window : float, optional

    Returns
    -------
    smo: smoothed version of the input flux array
    '''

    # This is SUPER slow... maybe useful in some places (LLC only?).
    # Can't be sped up much w/ indexing, because needs to move fixed
    # windows of time... thumbs down. Keeping code only because maybe useful someday

    smo = np.zeros_like(flux)

    w1 = np.where((time >= time[0] + window / 2.0) &
                  (time <= time[-1] + window / 2.0 ))[0]

    for i in range(0,len(w1)):
        x = np.where((time[w1] >= time[w1][i] - window / 2.0) &
                     (time[w1] <= time[w1][i] + window / 2.0))

        fit = np.polyfit(time[w1][x], flux[w1][x], order,
                          w = (1. / error[w1][x]) )

        smo[w1[i]] = np.polyval(fit, time[w1][i])

    return smo


def GapFlat(time, flux, order=3, maxgap=0.125):
    '''
    Find gaps in data and then flatten within each continuous portion. Flatten
    done using polynomials

    Parameters
    ----------
    time : 1-d numpy array
    flux : 1-d numpy array
    order : int, optional
        the polynomial order to flatten each continuous region with (Default=3)
    maxgap : float, optional
        the maximum amount of time allowed between datapoints before a "gap" is
        found. (Default=0.125, units=days)

    Returns
    -------
    Flux array with polymonials removed
    '''
    _, dlr = FindGaps(time, maxgap=maxgap) # finds right edge of time windows

    tot_med = np.nanmedian(flux) # the total from all quarters

    flux_flat = np.array(flux, copy=True)

    for (le,ri) in dlr:
        krnl = int(float(ri-le) / 100.0)
        if (krnl < 10):
            krnl = 10
        flux_sm = np.array(pd.Series(flux).iloc[le:ri].rolling(krnl).median())
        indx = np.isfinite(flux_sm)
        fit = np.polyfit(time[le:ri][indx], flux_sm[indx], order)
        flux_flat[le:ri] = flux[le:ri] - np.polyval(fit, time[le:ri]) + tot_med

    return flux_flat


def QtrFlat(time, flux, qtr, order=3):
    '''
    Step thru each unique quarter of data, subtract polynomial fit to each quarter.
    Removes simple quarter-to-quarter variations.

    Note: ignores long/short cadence. Deal with on user end if needed

    Parameters
    ----------
    time : 1-d numpy array
    flux : 1-d numpy array
    qtr :  1-d numpy array
        the Kepler Quarter ID's to be iterated over.
    order : int, optional
        the polynomial order to flatten each continuous region with (Default=3)

    Returns
    -------
    Flux array polymonials removed from each quarter
    '''

    uQtr = np.unique(qtr)

    tot_med = np.nanmedian(flux) # the total from all quarters

    df = pd.DataFrame({'flux':flux,'time':time,'flux_flat':np.ones_like(flux) * tot_med,'qtr':qtr})
    flux_flat = pd.Series(df.flux_flat)


    for q in uQtr:
        # find all epochs within each Qtr, but careful w/ floats
        df = df[np.abs(df.qtr-q) < 0.1]
        krnl = int(float(df.shape[0]) / 100.0)
        if (krnl < 10):
            krnl = 10

        df['flux_sm'] = df.flux.rolling(krnl,center=False).median()
        df = df.dropna(how='any')

        fit = np.polyfit(np.array(df.time), np.array(df.flux_sm), order)
        flux_flat.iloc[df.index.values] = df.flux - np.polyval(fit, df.time) + tot_med

    return np.array(flux_flat)


def FindGaps(time, maxgap=0.125, return_LR=True, minspan=2.0):
    '''
    Find gaps in the time array of a light curve, return locations of the gaps.

    Note: assumes data is already sorted in time

    Parameters
    ----------
    time : 1-d numpy array
    maxgap : float, optional
        the maximum amount of time allowed between datapoints before a "gap" is
        found. (Default=0.125, units=days)
    return_LR : bool, optional
        decide if the Left and Right edges should be returned as separate
        arrays (default=True)

    Returns
    -------
    gap_out : array of gap edge indicies, including:
        [0, left edges, N], where N is len(time)

    if return_LR == True, then also return the Left and Right edges as separate arrays:
    gap_out, left, right
    '''

    # assumes data is already sorted!
    dt = time[1:] - time[:-1]
    gap = np.where((dt >= maxgap))[0]

    # add start/end of LC to loop over easily
    gap_out = np.append(0, np.append(gap, len(time)))

    right = np.append(gap + 1, len(time)) # right end of data
    left = np.append(0, gap + 1) # left start of data

    # remove gaps that are too close together

    # ok = np.where((time[right]-time[left] >= minspan))[0]
    # bad = np.where((time[right]-time[left] < minspan))[0]
    # for k in range(1,len(bad)-1):
        # for each bad span of data, figure out if it can be tacked on

    if return_LR:
        return gap_out, left, right
    else:
        return gap_out


def _sinfunc(t, per, amp, t0, yoff):
    '''
    Simple function defining a single Sine curve for use in curve_fit applications
    Defined as:
        F = sin( (t - t0) * 2 pi / period ) * amplitude + offset

    Parameters
    ----------
    t : 1-d numpy array
        array of times
    per : float
        sin period
    amp : float
        amplitude
    t0 : float
        phase zero-point
    yoff : float
        linear offset

    Returns
    -------
    F, array of fluxes defined by sine function
    '''

    return np.sin((t - t0) * 2.0 * np.pi / per) * amp  + yoff


def _sinfunc2(t, per1, amp1, t01, per2, amp2, t02, yoff):
    '''
    Simple function defining two Sine curves for use in curve_fit applications
    Defined as:
        F = sin( (t - t0_1) * 2 pi / period_1 ) * amplitude_1 + \
            sin( (t - t0_2) * 2 pi / period_2 ) * amplitude_2 + offset

    Parameters
    ----------
    t : 1-d numpy array
        array of times
    per1 : float
        sin period 1
    amp1 : float
        amplitude 1
    t01 : float
        phase zero-point 1
    per2 : float
        sin period 2
    amp2 : float
        amplitude 2
    t02 : float
        phase zero-point 2
    yoff : float
        linear offset

    Returns
    -------
    F, array of fluxes defined by sine function
    '''

    output = np.sin((t - t01) * 2.0 * np.pi / per1) * amp1 + \
             np.sin((t - t02) * 2.0 * np.pi / per2) * amp2 + yoff
    return output


def FitSin(time, flux, error, maxnum=5, nper=20000,
           minper=0.1, maxper=30.0, plim=0.25,
           per2=False, returnmodel=True, debug=False):
    '''
    Use Lomb Scargle to find a periodic signal. If it is significant then fit
    a sine curve and subtract. Repeat this procedure until no more periodic
    signals are found, or until maximum number of iterations has been reached.

    Note: this is where major issues were found in the light curve fitting as
    of Davenport (2016), where the iterative fitting was not adequately
    subtracting "pointy" features, such as RR Lyr or EBs. Upgrades to the
    fitting step are needed! Or, don't use iterative sine fitting...

    Idea for future: if L-S returns a significant P, use a median fit of the
    phase-folded data at that P instead of a sine fit...

    Parameters
    ----------
    time : 1-d numpy array
    flux : 1-d numpy array
    error : 1-d numpy array
    maxnum : int, optional
        maximum number of iterations to try finding periods at
        (default=5)
    nper : int, optional
        number of periods to search over with Lomb Scargle
        (defeault=20000)
    minper : float, optional
        minimum period (in units of time array, nominally days) to search
        for periods over (default=0.1)
    maxper : float, optional
        maximum period (in units of time array, nominally days) to search
        for periods over (default=30.0)
    plim : float, optional
        Lomb-Scargle power threshold needed to define a "significant" period
        (default=0.25)
    per2 : bool, optional
        if True, use the 2-sine model fit at each period. if False, use normal
        1-sine model (default=False)
    returnmodel : bool, optional
        if True, return the combined sine model. If False, return the
        data - model (default=True)
    debug : bool, optional
        used to print out troubleshooting things (default=False)

    Returns
    -------
    If returnmodel=True, output = combined sine model (default=True)
    If returnmodel=False, output = (data - model)
    '''

    flux_out = np.array(flux, copy=True)
    sin_out = np.zeros_like(flux) # return the sin function!

    # total baseline of time window
    dt = np.nanmax(time) - np.nanmin(time)

    medflux = np.nanmedian(flux)
    # ti = time[dl[i]:dr[i]]

    for k in range(0, maxnum):
        # Use Jake Vanderplas faster version!
        pgram = LombScargleFast(fit_offset=False)
        pgram.optimizer.set(period_range=(minper,maxper))
        pgram = pgram.fit(time,
                          flux_out - medflux,
                          error)

        df = (1./minper - 1./maxper) / nper
        f0 = 1./maxper
        pwr = pgram.score_frequency_grid(f0, df, nper)

        freq = f0 + df * np.arange(nper)
        per = 1./freq

        pok = np.where((per < dt) & (per > minper))
        pk = per[pok][np.argmax(pwr[pok])]
        pp = np.max(pwr)

        if debug is True:
            print('trial (k): '+str(k)+'.  peak period (pk):'+str(pk)+
                  '.  peak power (pp):'+str(pp))

        # if a period w/ enough power is detected
        if (pp > plim):
            # fit sin curve to window and subtract
            if per2 is True:
                p0 = [pk, 3.0 * np.nanstd(flux_out-medflux), 0.0,
                      pk/2., 1.5 * np.nanstd(flux_out-medflux), 0.1, 0.0]
                try:
                    pfit, pcov = curve_fit(_sinfunc2, time, flux_out-medflux, p0=p0)
                    if debug is True:
                        print('>>', pfit)
                except RuntimeError:
                    pfit = [pk, 0., 0., 0., 0., 0., 0.]
                    if debug is True:
                        print('Curve_Fit2 no good')

                flux_out = flux_out - _sinfunc2(time, *pfit)
                sin_out = sin_out + _sinfunc2(time, *pfit)

            else:
                p0 = [pk, 3.0 * np.nanstd(flux_out-medflux), 0.0, 0.0]
                try:
                    pfit, pcov = curve_fit(_sinfunc, time, flux_out-medflux, p0=p0)
                except RuntimeError:
                    pfit = [pk, 0., 0., 0.]
                    if debug is True:
                        print('Curve_Fit no good')

                flux_out = flux_out - _sinfunc(time, *pfit)
                sin_out = sin_out + _sinfunc(time, *pfit)

        # add the median flux for this window BACK in
        sin_out = sin_out + medflux

    # if debug is True:
    #     plt.figure()
    #     plt.plot(time, flux)
    #     plt.plot(time, flux_out, c='red')
    #     plt.show()

    if returnmodel is True:
        return sin_out
    else:
        return flux_out


'''
def FitMedSin(time, flux, error, nper=20000,
              minper=0.1, maxper=30.0, plim=0.25,
              returnmodel=True ):

    flux_out = np.array(flux, copy=True)
    sin_out = np.zeros_like(flux) # return the sin function!

    # total baseline of time window
    dt = np.nanmax(time) - np.nanmin(time)

    medflux = np.nanmedian(flux)
    # ti = time[dl[i]:dr[i]]

    if np.nanmax(time) - np.nanmin(time) < maxper*2.:
        maxper = (np.nanmax(time) - np.nanmin(time))/2.


    # Use Jake Vanderplas supersmoother version
    pgram = SuperSmoother()
    pgram.optimizer.period_range=(minper,maxper)
    pgram = pgram.fit(time,
                      flux_out - medflux,
                      error)

    # Predict on a regular phase grid
    period = pgram.best_period

    phz = np.mod(time, period) / period
    ss = np.argsort(phz)
    magfit = np.zeros_like(phz)

    magfit[ss] = pgram.predict(phz[ss])

    if returnmodel is True:
        return magfit + medflux
    else:
        return flux - magfit
'''


def MultiBoxcar(time, flux, error, numpass=3, kernel=2.0,
                sigclip=5, pcentclip=5, returnindx=False,
                debug=False):
    '''
    Boxcar smoothing with multi-pass outlier rejection. Uses both errors
    and local scatter for rejection Uses Pandas rolling median filter.

    Parameters
    time : 1-d numpy array
    flux : 1-d numpy array
    error : 1-d numpy array
    numpass : int, optional
        the number of passes to make over the data. (Default = 3)
    kernel : float, optional
        the boxcar size in hours. (Default is 2.0)
        Note: using whole numbers is probably wise here.
    sigclip : int, optional
        Number of times the standard deviation to clip points at
        (Default is 5)
    pcentclip : int, optional
        % of data to clip for outliers, i.e. 5= keep 5th-95th percentile
        (Default is 5)
    debug : bool, optional
        used to print out troubleshooting things (default=False)

    Returns
    -------
    The smoothed light curve model
    '''

    # flux_sm = np.array(flux, copy=True)
    # time_sm = np.array(time, copy=True)
    # error_sm = np.array(error, copy=True)
    #
    # for returnindx = True
    # indx_out = []

    # the data within each gap range

    #This is annoying: https://pandas.pydata.org/pandas-docs/stable/gotchas.html#byte-ordering-issues
    #flux = flux.byteswap().newbyteorder()

    flux_i = pd.DataFrame({'flux':flux,'error_i':error,'time_i':time})
    time_i = np.array(time)
    #flux_i = pd.Series(flux)
    error_i = error
    indx_i = np.arange(len(time)) # for tracking final indx used
    exptime = np.nanmedian(time_i[1:]-time_i[:-1])

    nptsmooth = int(kernel/24.0 / exptime)

    if (nptsmooth < 4):
        nptsmooth = 4

    if debug is True:
        print('# of smoothing points: '+str(nptsmooth))

    # now take N passes of rejection on it
    for k in range(0, numpass):
        # rolling median in this data span with the kernel size
        flux_i['flux_i_sm'] = flux_i.flux.rolling(nptsmooth, center=True).median()
        #indx = np.isfinite(flux_i_sm)
        flux_i = flux_i.dropna(how='any')

        if (flux_i.shape[0] > 1):
            #diff_k = (flux_i[indx] - flux_i_sm[indx])
            flux_i['diff_k'] = flux_i.flux-flux_i.flux_i_sm
            lims = np.nanpercentile(flux_i.diff_k, (pcentclip, 100-pcentclip))

            # iteratively reject points
            # keep points within sigclip (for phot errors), or
            # within percentile clip (for scatter)
            #ok = np.logical_or((np.abs(diff_k / error_i[indx]) < sigclip),
                              # (lims[0] < diff_k) * (diff_k < lims[1]))
            ok = np.logical_or((np.abs(flux_i.diff_k / flux_i.error_i) < sigclip),
                               (lims[0] < flux_i.diff_k) * (flux_i.diff_k < lims[1]))
            if debug is True:
                print('k = '+str(k))
                print('number of accepted points: '+str(len(ok[0])))

            #time_i = time_i[indx][ok]
            #flux_i = flux_i[indx][ok]
            #error_i = error_i[indx][ok]
            #indx_i = indx_i[indx][ok]
            flux_i = flux_i[ok]


    flux_sm = np.interp(time, flux_i.time_i, flux_i.flux)

    indx_out = flux_i.index.values

    if returnindx is False:
        return flux_sm
    else:
        return np.array(indx_out, dtype='int')


def IRLSSpline(time, flux, error, Q=400.0, ksep=0.07, numpass=5, order=3, debug=False):
    '''
    IRLS = Iterative Re-weight Least Squares
    Do a multi-pass, weighted spline fit, with iterative down-weighting of
    outliers. This is a simple, highly flexible approach. Suspiciously good
    at times...

    Originally described by DFM: https://github.com/dfm/untrendy
    Likley not adequately reproduced here.

    uses scipy.interpolate.LSQUnivariateSpline

    Parameters
    ----------
    time : 1-d numpy array
    flux : 1-d numpy array
    error : 1-d numpy array
    Q : float, optional
        the penalty factor to give outlier data in subsequent passes
        (deafult is 400.0)
    ksep : float, optional
        the spline knot separation, in units of the light curve time
        (default is 0.07)
    numpass : int, optional
        the number of passes to take over the data (default is 5)
    order : int, optional
        the spline order to use (default is 3)
    debug : bool, optional
        used to print out troubleshooting things (default=False)

    Returns
    -------
    the final spline model
    '''

    weight = 1. / (error**2.0)

    knots = np.arange(np.nanmin(time) + ksep, np.nanmax(time) - ksep, ksep)

    if debug is True:
        print('IRLSSpline: knots: ', np.shape(knots))
        print('IRLSSpline: time: ', np.shape(time), np.nanmin(time), time[0], np.nanmax(time), time[-1])
        print('IRLSSpline: <weight> = ', np.mean(weight))
        print(np.where((time[1:] - time[:-1] < 0))[0])

        plt.figure()
        plt.errorbar(time, flux, error)
        plt.scatter(knots, knots*0. + np.median(flux))
        plt.show()

    for k in range(numpass):
        spl = LSQUnivariateSpline(time, flux, knots, k=order, check_finite=True, w=weight)
        # spl = UnivariateSpline(time, flux, w=weight, k=order, s=1)

        chisq = ((flux - spl(time))**2.) / (error**2.0)

        weight = Q / ((error**2.0) * (chisq + Q))

    return spl(time)

